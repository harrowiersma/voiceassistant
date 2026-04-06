"""
Call handler — the orchestrator that wires AudioSocket ↔ STT ↔ LLM ↔ TTS.

CRITICAL: Asterisk's app_audiosocket has a 2-second inactivity timeout.
We MUST send audio frames (even silence) continuously or the call drops.
"""
import asyncio
import json
import logging
import struct
import subprocess
from datetime import datetime

from engine.audiosocket import AUDIO_TYPE, HANGUP_TYPE, AudioSocketProtocol, read_frame
from engine.call_session import CallSession
from engine.routing import resolve_persona
from engine.post_call import log_call, process_post_call_actions
from engine.tts_cache import TTSCache
from app.helpers import get_config
from db.init_db import DEFAULT_DB_PATH

logger = logging.getLogger(__name__)

# Audio settings
ASTERISK_SAMPLE_RATE = 8000
ASTERISK_SAMPLE_WIDTH = 2  # 16-bit
SILENCE_THRESHOLD = 500
SILENCE_DURATION_MS = 1500
SPEECH_MIN_MS = 300

# Piper TTS binary (inside venv)
PIPER_BIN = "/opt/voice-secretary/.venv/bin/piper"
PIPER_MODEL_DIR = "/opt/voice-secretary/models/piper"

# Pre-loaded Vosk model (set by init_vosk_model())
_vosk_model = None


def init_vosk_model():
    """Pre-load Vosk STT model at engine startup. Call once from __main__.py."""
    global _vosk_model
    try:
        import vosk
        vosk.SetLogLevel(-1)
        _vosk_model = vosk.Model("/opt/voice-secretary/models/vosk/model")
        logger.info("Vosk STT model pre-loaded")
    except Exception as e:
        logger.error(f"Failed to pre-load Vosk model: {e}")
        _vosk_model = None


# 320 bytes = 20ms of silence at 8kHz 16-bit mono
SILENCE_FRAME = AudioSocketProtocol.build_audio_frame(b'\x00' * 320)


def _rms(audio: bytes) -> float:
    """Calculate RMS amplitude of audio buffer."""
    if not audio or len(audio) < 2:
        return 0
    samples = struct.unpack(f"<{len(audio) // 2}h", audio)
    return (sum(s * s for s in samples) / len(samples)) ** 0.5 if samples else 0


def _synthesize_tts_sync(text: str, db_path: str = None) -> bytes:
    """Synthesize text to 8kHz PCM via Piper. Blocking — run in executor."""
    voice = get_config("ai.tts_voice", default="en-us-amy-medium", db_path=db_path)
    model_path = f"{PIPER_MODEL_DIR}/{voice}.onnx"
    try:
        result = subprocess.run(
            [PIPER_BIN, "--model", model_path, "--output_raw"],
            input=text.encode(), capture_output=True, timeout=30,
        )
        if result.returncode != 0:
            logger.error(f"Piper failed: {result.stderr.decode()[:200]}")
            return b""
        # Piper outputs 22050Hz 16-bit — downsample to 8000Hz
        raw = result.stdout
        if len(raw) < 4:
            return b""
        samples = struct.unpack(f"<{len(raw) // 2}h", raw)
        ratio = 22050 / 8000
        down = [samples[int(i * ratio)] for i in range(int(len(samples) / ratio)) if int(i * ratio) < len(samples)]
        return struct.pack(f"<{len(down)}h", *down)
    except Exception as e:
        logger.error(f"TTS error: {e}")
        return b""


async def _keep_alive(writer: asyncio.StreamWriter, stop: asyncio.Event):
    """Send silence frames every 20ms to prevent Asterisk 2s timeout."""
    try:
        while not stop.is_set():
            writer.write(SILENCE_FRAME)
            await writer.drain()
            await asyncio.sleep(0.02)
    except (ConnectionResetError, BrokenPipeError):
        pass


async def _send_audio(writer: asyncio.StreamWriter, audio_pcm: bytes):
    """Send PCM audio to Asterisk via AudioSocket in 20ms chunks."""
    chunk_size = 320  # 20ms at 8kHz 16-bit mono
    for i in range(0, len(audio_pcm), chunk_size):
        chunk = audio_pcm[i:i + chunk_size]
        # Pad last chunk if needed
        if len(chunk) < chunk_size:
            chunk = chunk + b'\x00' * (chunk_size - len(chunk))
        writer.write(AudioSocketProtocol.build_audio_frame(chunk))
        await writer.drain()
        await asyncio.sleep(0.02)


async def _synthesize_and_send(writer: asyncio.StreamWriter, text: str, db_path: str = None):
    """Synthesize TTS and send audio. Sends silence while Piper is working."""
    if not text:
        return
    logger.info(f"TTS: {text[:80]}...")

    # Start sending silence to keep the connection alive
    stop_silence = asyncio.Event()
    silence_task = asyncio.create_task(_keep_alive(writer, stop_silence))

    try:
        # Run Piper in thread pool (blocking subprocess)
        loop = asyncio.get_event_loop()
        audio = await loop.run_in_executor(None, _synthesize_tts_sync, text, db_path)
    finally:
        # Stop silence and send actual audio
        stop_silence.set()
        await silence_task

    if audio:
        await _send_audio(writer, audio)
        logger.info(f"TTS sent: {len(audio)} bytes")
    else:
        logger.warning("TTS produced no audio")


async def handle_call(call_uuid, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Handle one phone call: AudioSocket ↔ STT ↔ LLM ↔ TTS pipeline."""
    db_path = DEFAULT_DB_PATH
    caller_number = "unknown"
    started_at = datetime.now()

    logger.info(f"Call started: {call_uuid}")

    # IMMEDIATELY start sending silence to prevent 2s timeout
    stop_initial_silence = asyncio.Event()
    initial_silence = asyncio.create_task(_keep_alive(writer, stop_initial_silence))

    try:
        # Resolve persona
        persona = resolve_persona(caller_number, db_path)
        persona_id = persona["id"] if persona else None

        # Check blocked numbers
        from db.connection import get_db_connection
        conn = get_db_connection(db_path)
        blocked = conn.execute(
            "SELECT * FROM blocked_numbers WHERE block_type = 'exact' AND pattern = ?",
            (caller_number,),
        ).fetchone()
        if not blocked:
            for b in conn.execute("SELECT * FROM blocked_numbers WHERE block_type = 'prefix'").fetchall():
                if caller_number.startswith(dict(b)["pattern"]):
                    blocked = b
                    break
        conn.close()

        if blocked:
            logger.info(f"Blocked caller: {caller_number}")
            stop_initial_silence.set()
            await initial_silence
            writer.write(AudioSocketProtocol.build_hangup_frame())
            await writer.drain()
            writer.close()
            return

        # Create call session
        session = CallSession(caller_number=caller_number, db_path=db_path, persona_id=persona_id)

        # Create Vosk recognizer from pre-loaded model
        recognizer = None
        if _vosk_model:
            import vosk
            recognizer = vosk.KaldiRecognizer(_vosk_model, ASTERISK_SAMPLE_RATE)
            logger.info("Vosk recognizer ready")

        # Stop initial silence — we'll send the greeting now
        stop_initial_silence.set()
        await initial_silence

        # Send greeting (with silence keepalive during TTS synthesis)
        if session.vacation_active:
            logger.info("Vacation mode active")
            await _synthesize_and_send(writer, session.vacation_message, db_path)
            await _synthesize_and_send(writer, "Would you like to leave a message?", db_path)
        else:
            greeting = session.get_greeting_text()
            await _synthesize_and_send(writer, greeting, db_path)

        # Main conversation loop
        audio_buffer = bytearray()
        silence_frames = 0
        speech_frames = 0
        is_speaking = False
        turn_count = 0
        call_ended = False

        while not call_ended and turn_count < 20:
            try:
                msg_type, payload = await asyncio.wait_for(read_frame(reader), timeout=30.0)
            except asyncio.TimeoutError:
                logger.info(f"Call {call_uuid}: timeout")
                await _synthesize_and_send(writer, "I haven't heard anything. Goodbye!", db_path)
                break
            except asyncio.IncompleteReadError:
                logger.info(f"Call {call_uuid}: caller hung up")
                break

            if msg_type == HANGUP_TYPE:
                logger.info(f"Call {call_uuid}: hangup")
                break

            if msg_type != AUDIO_TYPE:
                continue

            # Speech/silence detection
            audio_buffer.extend(payload)
            rms = _rms(payload)

            if rms > SILENCE_THRESHOLD:
                is_speaking = True
                speech_frames += 1
                silence_frames = 0
            else:
                silence_frames += 1

            frame_ms = (len(payload) / (ASTERISK_SAMPLE_RATE * ASTERISK_SAMPLE_WIDTH)) * 1000
            silence_ms = silence_frames * frame_ms
            speech_ms = speech_frames * frame_ms

            # End of utterance
            if is_speaking and silence_ms >= SILENCE_DURATION_MS and speech_ms >= SPEECH_MIN_MS:
                turn_count += 1
                is_speaking = False
                speech_frames = 0
                silence_frames = 0

                # Transcribe
                transcript = ""
                if recognizer:
                    recognizer.AcceptWaveform(bytes(audio_buffer))
                    result = json.loads(recognizer.FinalResult())
                    transcript = result.get("text", "").strip()
                audio_buffer.clear()
                logger.info(f"STT [{turn_count}]: '{transcript}'")

                # LLM
                response_text = session.process_turn(transcript)
                logger.info(f"LLM [{turn_count}]: '{response_text[:100]}'")

                # Handle actions
                if session.action_taken == "forwarded":
                    await _synthesize_and_send(writer, response_text, db_path)
                    forward_number = get_config("sip.forward_number", db_path=db_path)
                    if forward_number:
                        logger.info(f"Forwarding to {forward_number}")
                        try:
                            subprocess.run(
                                ["/usr/sbin/asterisk", "-rx",
                                 f"channel redirect {call_uuid} forward,s,1"],
                                capture_output=True, timeout=5,
                            )
                        except Exception as e:
                            logger.error(f"Forward failed: {e}")
                    call_ended = True
                    continue

                if session.state == "ending":
                    await _synthesize_and_send(writer, response_text, db_path)
                    call_ended = True
                    continue

                await _synthesize_and_send(writer, response_text, db_path)

            # Prevent buffer overflow
            if len(audio_buffer) > ASTERISK_SAMPLE_RATE * ASTERISK_SAMPLE_WIDTH * 30:
                audio_buffer.clear()
                speech_frames = 0

    except Exception as e:
        logger.error(f"Call {call_uuid} error: {e}", exc_info=True)
    finally:
        # Log call
        duration = int((datetime.now() - started_at).total_seconds())
        summary = session.end_call(reason="completed") if 'session' in dir() else {"action_taken": "error"}

        try:
            call_id = log_call(
                db_path=db_path, caller_number=caller_number,
                caller_name=summary.get("caller_name", "Unknown"),
                reason=summary.get("reason", ""),
                transcript=summary.get("transcript", []),
                action_taken=summary.get("action_taken", "ended"),
                duration_seconds=duration,
            )
            process_post_call_actions(
                db_path=db_path, call_id=call_id,
                caller_name=summary.get("caller_name", "Unknown"),
                caller_number=caller_number,
                reason=summary.get("reason", ""),
                transcript=str(summary.get("transcript", [])),
                action_taken=summary.get("action_taken", "ended"),
            )
        except Exception as e:
            logger.error(f"Post-call failed: {e}")

        try:
            writer.write(AudioSocketProtocol.build_hangup_frame())
            await writer.drain()
        except Exception:
            pass

        try:
            writer.close()
        except Exception:
            pass

        logger.info(f"Call {call_uuid} ended: {duration}s action={summary.get('action_taken')}")
