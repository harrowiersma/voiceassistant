"""
Call handler — wires AudioSocket ↔ STT ↔ LLM ↔ TTS.

CRITICAL: Asterisk app_audiosocket has a 2-second inactivity timeout.
We MUST send audio frames continuously or the call drops.
Solution: a background task sends silence frames every 20ms for the
entire call duration. TTS and conversation happen on top of that.
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
from app.helpers import get_config
from db.init_db import DEFAULT_DB_PATH

logger = logging.getLogger(__name__)

ASTERISK_SAMPLE_RATE = 8000
ASTERISK_SAMPLE_WIDTH = 2
SILENCE_THRESHOLD = 500
SILENCE_DURATION_MS = 1500
SPEECH_MIN_MS = 300

PIPER_BIN = "/opt/voice-secretary/.venv/bin/piper"
PIPER_MODEL_DIR = "/opt/voice-secretary/models/piper"

# Pre-loaded Vosk model
_vosk_model = None

# Pre-built silence frame (20ms at 8kHz 16-bit mono = 320 bytes)
_SILENCE_PCM = b'\x00' * 320
_SILENCE_FRAME = AudioSocketProtocol.build_audio_frame(_SILENCE_PCM)


def init_vosk_model():
    """Pre-load Vosk STT model at engine startup."""
    global _vosk_model
    try:
        import vosk
        vosk.SetLogLevel(-1)
        _vosk_model = vosk.Model("/opt/voice-secretary/models/vosk/model")
        logger.info("Vosk STT model pre-loaded")
    except Exception as e:
        logger.error(f"Failed to pre-load Vosk: {e}")


def _rms(audio: bytes) -> float:
    if not audio or len(audio) < 2:
        return 0
    samples = struct.unpack(f"<{len(audio) // 2}h", audio)
    return (sum(s * s for s in samples) / len(samples)) ** 0.5 if samples else 0


def _synthesize_tts_sync(text: str, db_path: str = None) -> bytes:
    """Synthesize text to 8kHz signed-linear PCM via Piper + sox resampling."""
    voice = get_config("ai.tts_voice", default="en-us-amy-medium", db_path=db_path)
    model_path = f"{PIPER_MODEL_DIR}/{voice}.onnx"
    try:
        # Piper → raw 22050Hz → sox resample to 8000Hz
        # Pipeline: piper --output_raw | sox -t raw -r 22050 -b 16 -e signed -c 1 - -t raw -r 8000 -
        piper_proc = subprocess.Popen(
            [PIPER_BIN, "--model", model_path, "--output_raw"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        sox_proc = subprocess.Popen(
            ["sox", "-t", "raw", "-r", "22050", "-b", "16", "-e", "signed-integer",
             "-c", "1", "-L", "-",  # input: raw 22050Hz 16-bit LE mono from stdin
             "-t", "raw", "-r", "8000", "-b", "16", "-e", "signed-integer",
             "-c", "1", "-L", "-"],  # output: raw 8000Hz 16-bit LE mono to stdout
            stdin=piper_proc.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        piper_proc.stdin.write(text.encode())
        piper_proc.stdin.close()
        piper_proc.stdout.close()  # Allow sox to receive EOF when piper finishes

        pcm_8k, sox_err = sox_proc.communicate(timeout=30)
        piper_proc.wait(timeout=5)

        if sox_proc.returncode != 0:
            logger.error(f"Sox failed: {sox_err.decode()[:200]}")
            return b""
        return pcm_8k
    except Exception as e:
        logger.error(f"TTS error: {e}")
        return b""


class AudioBridge:
    """Manages the AudioSocket write stream. Sends silence continuously,
    and can be interrupted to send TTS audio instead."""

    def __init__(self, writer: asyncio.StreamWriter):
        self.writer = writer
        self._playing = asyncio.Event()  # Set when TTS audio is being played
        self._alive = True
        self._task = None

    async def start(self):
        """Start the background silence sender."""
        self._task = asyncio.create_task(self._run())

    async def _run(self):
        """Send silence frames every 20ms unless TTS is playing."""
        try:
            while self._alive:
                if not self._playing.is_set():
                    self.writer.write(_SILENCE_FRAME)
                    await self.writer.drain()
                await asyncio.sleep(0.02)
        except (ConnectionResetError, BrokenPipeError, ConnectionError):
            logger.debug("AudioBridge: connection closed")
        except Exception as e:
            logger.error(f"AudioBridge error: {e}")

    async def play_audio(self, pcm: bytes):
        """Send PCM audio, pausing the silence sender."""
        self._playing.set()
        try:
            chunk_size = 320
            for i in range(0, len(pcm), chunk_size):
                if not self._alive:
                    break
                chunk = pcm[i:i + chunk_size]
                if len(chunk) < chunk_size:
                    chunk += b'\x00' * (chunk_size - len(chunk))
                self.writer.write(AudioSocketProtocol.build_audio_frame(chunk))
                await self.writer.drain()
                await asyncio.sleep(0.02)
        finally:
            self._playing.clear()

    async def synthesize_and_play(self, text: str, db_path: str = None):
        """Synthesize TTS in background thread, then play audio."""
        if not text:
            return
        logger.info(f"TTS: {text[:80]}...")
        loop = asyncio.get_event_loop()
        audio = await loop.run_in_executor(None, _synthesize_tts_sync, text, db_path)
        if audio:
            await self.play_audio(audio)
            logger.info(f"TTS played: {len(audio)} bytes ({len(audio) / (8000*2):.1f}s)")
        else:
            logger.warning("TTS produced no audio")

    def stop(self):
        self._alive = False
        if self._task:
            self._task.cancel()


async def handle_call(call_uuid, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Handle one phone call."""
    db_path = DEFAULT_DB_PATH
    caller_number = "unknown"
    started_at = datetime.now()
    logger.info(f"Call started: {call_uuid}")

    # Start the audio bridge — sends silence continuously from this moment
    bridge = AudioBridge(writer)
    await bridge.start()

    session = None
    try:
        # Quick setup (all fast — no blocking)
        persona = resolve_persona(caller_number, db_path)
        persona_id = persona["id"] if persona else None

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
            bridge.stop()
            return

        session = CallSession(caller_number=caller_number, db_path=db_path, persona_id=persona_id)

        recognizer = None
        if _vosk_model:
            import vosk
            # Vosk model expects 16kHz — we'll resample 8kHz→16kHz before feeding
            recognizer = vosk.KaldiRecognizer(_vosk_model, 16000)

        # Send greeting (silence keeps flowing in background while Piper runs)
        if session.vacation_active:
            await bridge.synthesize_and_play(session.vacation_message, db_path)
            await bridge.synthesize_and_play("Would you like to leave a message?", db_path)
        else:
            await bridge.synthesize_and_play(session.get_greeting_text(), db_path)

        # Main conversation loop
        audio_buffer = bytearray()
        silence_frames = 0
        speech_frames = 0
        is_speaking = False
        turn_count = 0

        while turn_count < 20:
            try:
                msg_type, payload = await asyncio.wait_for(read_frame(reader), timeout=30.0)
            except asyncio.TimeoutError:
                await bridge.synthesize_and_play("I haven't heard anything. Goodbye!", db_path)
                break
            except (asyncio.IncompleteReadError, ConnectionResetError):
                logger.info(f"Call {call_uuid}: disconnected")
                break

            if msg_type == HANGUP_TYPE:
                logger.info(f"Call {call_uuid}: hangup")
                break

            if msg_type != AUDIO_TYPE:
                continue

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

            if is_speaking and silence_ms >= SILENCE_DURATION_MS and speech_ms >= SPEECH_MIN_MS:
                turn_count += 1
                is_speaking = False
                speech_frames = 0
                silence_frames = 0

                transcript = ""
                if recognizer:
                    # Resample 8kHz → 16kHz for Vosk (linear interpolation)
                    raw_8k = bytes(audio_buffer)
                    samples_8k = struct.unpack(f"<{len(raw_8k) // 2}h", raw_8k)
                    samples_16k = []
                    for i in range(len(samples_8k) - 1):
                        samples_16k.append(samples_8k[i])
                        samples_16k.append((samples_8k[i] + samples_8k[i + 1]) // 2)
                    if samples_8k:
                        samples_16k.append(samples_8k[-1])
                    raw_16k = struct.pack(f"<{len(samples_16k)}h", *samples_16k)
                    recognizer.AcceptWaveform(raw_16k)
                    result = json.loads(recognizer.FinalResult())
                    transcript = result.get("text", "").strip()
                audio_buffer.clear()
                logger.info(f"STT [{turn_count}]: '{transcript}'")

                response_text = session.process_turn(transcript)
                logger.info(f"LLM [{turn_count}]: '{response_text[:100]}'")

                if session.action_taken == "forwarded":
                    await bridge.synthesize_and_play(response_text, db_path)
                    fwd = get_config("sip.forward_number", db_path=db_path)
                    if fwd:
                        try:
                            subprocess.run(
                                ["/usr/sbin/asterisk", "-rx",
                                 f"channel redirect {call_uuid} forward,s,1"],
                                capture_output=True, timeout=5)
                        except Exception as e:
                            logger.error(f"Forward failed: {e}")
                    break

                if session.state == "ending":
                    await bridge.synthesize_and_play(response_text, db_path)
                    break

                await bridge.synthesize_and_play(response_text, db_path)

            if len(audio_buffer) > ASTERISK_SAMPLE_RATE * ASTERISK_SAMPLE_WIDTH * 30:
                audio_buffer.clear()
                speech_frames = 0

    except Exception as e:
        logger.error(f"Call {call_uuid} error: {e}", exc_info=True)
    finally:
        bridge.stop()

        duration = int((datetime.now() - started_at).total_seconds())
        summary = session.end_call(reason="completed") if session else {"action_taken": "error"}

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
            writer.close()
        except Exception:
            pass

        logger.info(f"Call {call_uuid} ended: {duration}s action={summary.get('action_taken')}")
