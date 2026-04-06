"""
Call handler — the orchestrator that wires AudioSocket ↔ STT ↔ LLM ↔ TTS.

This is the core of the voice secretary. For each incoming call:
1. Receive audio from Asterisk via AudioSocket
2. Transcribe speech to text via Vosk STT
3. Process text through CallSession (LLM with tool calling)
4. Synthesize response via Piper TTS
5. Send audio back to caller via AudioSocket
6. Handle call actions (forward, take message, end call)
7. Log call and send email summary on hangup
"""
import asyncio
import json
import logging
import struct
import wave
import io
import subprocess
from datetime import datetime

from engine.audiosocket import AUDIO_TYPE, HANGUP_TYPE, UUID_TYPE, AudioSocketProtocol, read_frame
from engine.call_session import CallSession
from engine.routing import resolve_persona
from engine.post_call import log_call, process_post_call_actions
from engine.tts_cache import TTSCache
from engine.thermal import ThermalMonitor
from app.helpers import get_config
from db.init_db import DEFAULT_DB_PATH

logger = logging.getLogger(__name__)

# Audio settings — Asterisk AudioSocket sends 8kHz 16-bit signed LE mono
ASTERISK_SAMPLE_RATE = 8000
ASTERISK_SAMPLE_WIDTH = 2  # 16-bit
VOSK_SAMPLE_RATE = 16000

# Silence detection
SILENCE_THRESHOLD = 500  # RMS amplitude below this = silence
SILENCE_DURATION_MS = 1500  # 1.5 seconds of silence = end of speech
SPEECH_MIN_MS = 300  # Minimum speech duration to process

# Thermal monitor (singleton)
_thermal = ThermalMonitor()


def _resample_8k_to_16k(audio_8k: bytes) -> bytes:
    """Resample 8kHz audio to 16kHz for Vosk (simple linear interpolation)."""
    samples = struct.unpack(f"<{len(audio_8k) // 2}h", audio_8k)
    resampled = []
    for i in range(len(samples) - 1):
        resampled.append(samples[i])
        resampled.append((samples[i] + samples[i + 1]) // 2)
    if samples:
        resampled.append(samples[-1])
    return struct.pack(f"<{len(resampled)}h", *resampled)


def _resample_16k_to_8k(audio_16k: bytes) -> bytes:
    """Resample 16kHz audio to 8kHz for Asterisk (downsample by dropping every other sample)."""
    samples = struct.unpack(f"<{len(audio_16k) // 2}h", audio_16k)
    downsampled = samples[::2]
    return struct.pack(f"<{len(downsampled)}h", *downsampled)


def _rms(audio: bytes) -> float:
    """Calculate RMS amplitude of audio buffer."""
    if not audio or len(audio) < 2:
        return 0
    samples = struct.unpack(f"<{len(audio) // 2}h", audio)
    if not samples:
        return 0
    return (sum(s * s for s in samples) / len(samples)) ** 0.5


def _synthesize_tts(text: str, db_path: str = None) -> bytes:
    """Synthesize text to 8kHz audio using Piper TTS. Returns raw PCM bytes."""
    voice = get_config("ai.tts_voice", default="en-us-amy-medium", db_path=db_path)
    model_dir = "/opt/voice-secretary/models/piper"
    model_path = f"{model_dir}/{voice}.onnx"

    try:
        # Piper outputs 22050Hz by default, we need to convert to 8kHz
        result = subprocess.run(
            ["piper", "--model", model_path, "--output_raw"],
            input=text.encode(),
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.error(f"Piper TTS failed: {result.stderr.decode()}")
            return b""

        # Piper outputs 16-bit signed LE at 22050Hz — resample to 8kHz
        raw_22k = result.stdout
        samples_22k = struct.unpack(f"<{len(raw_22k) // 2}h", raw_22k)

        # Downsample 22050 → 8000 (factor ~2.75)
        ratio = 22050 / 8000
        downsampled = []
        for i in range(int(len(samples_22k) / ratio)):
            idx = int(i * ratio)
            if idx < len(samples_22k):
                downsampled.append(samples_22k[idx])

        return struct.pack(f"<{len(downsampled)}h", *downsampled)
    except FileNotFoundError:
        logger.error("Piper binary not found — is piper-tts installed?")
        return b""
    except subprocess.TimeoutExpired:
        logger.error("Piper TTS timed out")
        return b""
    except Exception as e:
        logger.error(f"TTS error: {e}")
        return b""


async def _send_audio(writer: asyncio.StreamWriter, audio_pcm: bytes, chunk_size: int = 320):
    """Send PCM audio to Asterisk via AudioSocket in chunks (320 bytes = 20ms at 8kHz)."""
    for i in range(0, len(audio_pcm), chunk_size):
        chunk = audio_pcm[i:i + chunk_size]
        frame = AudioSocketProtocol.build_audio_frame(chunk)
        writer.write(frame)
        await writer.drain()
        # Pace at real-time (20ms per 320-byte chunk at 8kHz 16-bit mono)
        await asyncio.sleep(0.02)


async def _send_tts_response(writer: asyncio.StreamWriter, text: str, db_path: str = None):
    """Synthesize text and send audio to caller."""
    if not text:
        return
    logger.info(f"TTS: {text[:80]}...")
    audio = await asyncio.get_event_loop().run_in_executor(
        None, _synthesize_tts, text, db_path
    )
    if audio:
        await _send_audio(writer, audio)
    else:
        logger.warning("TTS produced no audio — caller hears silence")


async def handle_call(call_uuid, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Handle one phone call: AudioSocket ↔ STT ↔ LLM ↔ TTS pipeline."""
    db_path = DEFAULT_DB_PATH
    caller_number = "unknown"  # Will be set from Asterisk CDR or CALLERID
    started_at = datetime.now()

    logger.info(f"Call started: {call_uuid}")

    # Resolve persona by inbound number (default for now)
    persona = resolve_persona(caller_number, db_path)
    persona_id = persona["id"] if persona else None

    # Check if number is blocked
    from db.connection import get_db_connection
    conn = get_db_connection(db_path)
    blocked = conn.execute(
        "SELECT * FROM blocked_numbers WHERE block_type = 'exact' AND pattern = ?",
        (caller_number,),
    ).fetchone()
    if not blocked:
        # Check prefix blocks
        blocks = conn.execute("SELECT * FROM blocked_numbers WHERE block_type = 'prefix'").fetchall()
        for b in blocks:
            if caller_number.startswith(dict(b)["pattern"]):
                blocked = b
                break
    conn.close()

    if blocked:
        logger.info(f"Blocked caller: {caller_number} (reason: {dict(blocked).get('reason', 'N/A')})")
        writer.write(AudioSocketProtocol.build_hangup_frame())
        await writer.drain()
        writer.close()
        return

    # Create call session
    session = CallSession(
        caller_number=caller_number,
        db_path=db_path,
        persona_id=persona_id,
    )

    # Initialize STT
    try:
        import vosk
        vosk.SetLogLevel(-1)  # Suppress Vosk logs
        model_path = "/opt/voice-secretary/models/vosk/model"
        model = vosk.Model(model_path)
        recognizer = vosk.KaldiRecognizer(model, ASTERISK_SAMPLE_RATE)
        stt_available = True
        logger.info("Vosk STT loaded")
    except Exception as e:
        logger.error(f"Vosk STT not available: {e}")
        stt_available = False
        recognizer = None

    # Check for active vacation — play cached WAV and offer message
    if session.vacation_active:
        logger.info("Vacation mode active — playing vacation message")
        tts_cache = TTSCache(db_path=db_path)
        vac_path = tts_cache.get_vacation_path()
        if vac_path:
            # Play cached WAV
            try:
                with open(vac_path, "rb") as f:
                    audio = f.read()
                await _send_audio(writer, audio)
            except Exception:
                # Fall back to TTS
                await _send_tts_response(writer, session.vacation_message, db_path)
        else:
            await _send_tts_response(writer, session.vacation_message, db_path)

        # Brief pause then offer to take a message
        await asyncio.sleep(1)
        await _send_tts_response(
            writer,
            "If you'd like to leave a message, please speak after the tone. Otherwise, you may hang up.",
            db_path,
        )

    else:
        # Normal flow: send greeting
        greeting = session.get_greeting_text()
        await _send_tts_response(writer, greeting, db_path)

    # Main conversation loop
    audio_buffer = bytearray()
    silence_frames = 0
    speech_frames = 0
    is_speaking = False
    turn_count = 0
    max_turns = 20  # Safety limit
    call_ended = False

    try:
        while not call_ended and turn_count < max_turns:
            try:
                msg_type, payload = await asyncio.wait_for(read_frame(reader), timeout=30.0)
            except asyncio.TimeoutError:
                logger.info(f"Call {call_uuid}: 30s silence timeout")
                await _send_tts_response(writer, "I haven't heard anything. Goodbye!", db_path)
                break
            except asyncio.IncompleteReadError:
                logger.info(f"Call {call_uuid}: caller hung up")
                break

            if msg_type == HANGUP_TYPE:
                logger.info(f"Call {call_uuid}: hangup received")
                break

            if msg_type != AUDIO_TYPE:
                continue

            # Accumulate audio and detect speech/silence
            audio_buffer.extend(payload)
            rms = _rms(payload)

            if rms > SILENCE_THRESHOLD:
                is_speaking = True
                speech_frames += 1
                silence_frames = 0
            else:
                silence_frames += 1

            # Calculate silence duration (each frame is ~20ms at 8kHz with 320 bytes)
            frame_duration_ms = (len(payload) / (ASTERISK_SAMPLE_RATE * ASTERISK_SAMPLE_WIDTH)) * 1000
            silence_ms = silence_frames * frame_duration_ms
            speech_ms = speech_frames * frame_duration_ms

            # End of utterance: speech followed by silence
            if is_speaking and silence_ms >= SILENCE_DURATION_MS and speech_ms >= SPEECH_MIN_MS:
                turn_count += 1
                is_speaking = False
                speech_frames = 0
                silence_frames = 0

                # Transcribe the audio buffer
                if stt_available and recognizer:
                    audio_bytes = bytes(audio_buffer)

                    # Feed to Vosk
                    recognizer.AcceptWaveform(audio_bytes)
                    result = json.loads(recognizer.FinalResult())
                    transcript = result.get("text", "").strip()

                    logger.info(f"STT [{turn_count}]: '{transcript}'")
                else:
                    transcript = ""
                    logger.warning("STT not available — empty transcript")

                audio_buffer.clear()

                # Process through LLM
                response_text = session.process_turn(transcript)
                logger.info(f"LLM [{turn_count}]: '{response_text[:100]}...'")

                # Check for call actions
                if session.action_taken == "forwarded":
                    await _send_tts_response(writer, response_text, db_path)
                    # Transfer call via Asterisk AMI or redirect
                    forward_number = get_config("sip.forward_number", db_path=db_path)
                    if forward_number:
                        logger.info(f"Forwarding call to {forward_number}")
                        try:
                            subprocess.run(
                                ["/usr/sbin/asterisk", "-rx",
                                 f"channel redirect {call_uuid} forward,s,1"],
                                capture_output=True, timeout=5,
                            )
                        except Exception as e:
                            logger.error(f"Forward failed: {e}")
                            await _send_tts_response(
                                writer,
                                "I'm sorry, I wasn't able to connect you. May I take a message instead?",
                                db_path,
                            )
                            session.action_taken = None  # Reset to continue conversation
                    call_ended = True
                    continue

                if session.state == "ending":
                    await _send_tts_response(writer, response_text, db_path)
                    call_ended = True
                    continue

                # Send LLM response as speech
                await _send_tts_response(writer, response_text, db_path)

            # Reset buffer if it gets too large (prevent memory issues)
            if len(audio_buffer) > ASTERISK_SAMPLE_RATE * ASTERISK_SAMPLE_WIDTH * 30:
                logger.warning("Audio buffer overflow — clearing")
                audio_buffer.clear()
                speech_frames = 0

    except Exception as e:
        logger.error(f"Call {call_uuid} error: {e}", exc_info=True)
    finally:
        # Log the call and run post-call actions
        duration = int((datetime.now() - started_at).total_seconds())
        summary = session.end_call(reason="completed")

        try:
            call_id = log_call(
                db_path=db_path,
                caller_number=caller_number,
                caller_name=summary.get("caller_name", "Unknown"),
                reason=summary.get("reason", ""),
                transcript=summary.get("transcript", []),
                action_taken=summary.get("action_taken", "ended"),
                duration_seconds=duration,
            )
            process_post_call_actions(
                db_path=db_path,
                call_id=call_id,
                caller_name=summary.get("caller_name", "Unknown"),
                caller_number=caller_number,
                reason=summary.get("reason", ""),
                transcript=str(summary.get("transcript", [])),
                action_taken=summary.get("action_taken", "ended"),
            )
        except Exception as e:
            logger.error(f"Post-call actions failed: {e}")

        # Send hangup
        try:
            writer.write(AudioSocketProtocol.build_hangup_frame())
            await writer.drain()
        except Exception:
            pass

        writer.close()
        logger.info(f"Call {call_uuid} ended: duration={duration}s action={summary.get('action_taken')}")
