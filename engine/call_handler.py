"""
Call handler — wires AudioSocket ↔ STT ↔ LLM ↔ TTS.

STREAMING PIPELINE: LLM tokens stream in, get buffered into sentences,
each sentence is synthesized and played immediately. The caller hears
the first sentence ~2-3s after speaking instead of ~18s.

CRITICAL: Asterisk app_audiosocket has a 2-second inactivity timeout.
We MUST send audio frames continuously or the call drops.
"""
import asyncio
import json
import logging
import math
import os
import re
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

# Pre-cached audio (greeting per persona, common phrases per person)
_greeting_cache = {}   # persona_id → PCM bytes
_phrase_cache = {}     # phrase string → PCM bytes
_person_names = {}     # persona_id → [(name_lower, aliases_list, forward_number, person_id)]


def init_audio_cache(db_path=None):
    """Pre-synthesize greetings and common phrases at startup. Runs in ~30s."""
    global _greeting_cache, _phrase_cache, _person_names
    db_path = db_path or DEFAULT_DB_PATH
    from db.connection import get_db_connection
    conn = get_db_connection(db_path)

    # Cache greetings per persona
    personas = conn.execute("SELECT id, greeting, company_name FROM personas WHERE enabled = 1").fetchall()
    for p in personas:
        greeting = p["greeting"].replace("{company}", p["company_name"] or "")
        if greeting:
            logger.info(f"Caching greeting for persona {p['id']}: {greeting[:50]}...")
            pcm = _synthesize_tts_sync(greeting, db_path)
            if pcm:
                _greeting_cache[p["id"]] = pcm

    # Build person name lookup and cache connecting phrases
    persons = conn.execute(
        "SELECT id, name, aliases, forward_number, persona_id FROM persons WHERE enabled = 1"
    ).fetchall()
    for person in persons:
        pid = person["persona_id"]
        if pid not in _person_names:
            _person_names[pid] = []

        names = [person["name"].lower()]
        if person["aliases"]:
            names.extend([a.strip().lower() for a in person["aliases"].split(",") if a.strip()])

        _person_names[pid].append((person["name"], names, person["forward_number"], person["id"]))

        # Cache "Connecting you to [Name] now."
        phrase = f"Connecting you to {person['name']} now."
        logger.info(f"Caching phrase: {phrase}")
        pcm = _synthesize_tts_sync(phrase, db_path)
        if pcm:
            _phrase_cache[phrase] = pcm

    # Cache common phrases
    for phrase in [
        "Are you still there?",
        "Would you like to leave a message?",
        "Thank you, goodbye.",
        "Let me take a message for you.",
    ]:
        logger.info(f"Caching phrase: {phrase}")
        pcm = _synthesize_tts_sync(phrase, db_path)
        if pcm:
            _phrase_cache[phrase] = pcm

    conn.close()
    logger.info(f"Audio cache ready: {len(_greeting_cache)} greetings, {len(_phrase_cache)} phrases, {len(_person_names)} persona name-sets")


def _match_person_in_transcript(transcript, persona_id):
    """Check if transcript mentions a team member by name using fuzzy matching.

    Vosk consistently mangles unusual names — "Harro" becomes "her", "hero",
    "horror", "iraq", "horrible". We use character overlap + phonetic proximity
    to catch these misrecognitions.
    Returns (name, forward_number, person_id) or None.
    """
    if persona_id not in _person_names:
        return None
    spoken = transcript.lower()
    spoken_words = spoken.split()

    for display_name, name_variants, fwd_number, person_id in _person_names[persona_id]:
        if not fwd_number:
            continue
        for name in name_variants:
            # 1. Exact substring match
            if name in spoken:
                logger.info(f"Name exact match: '{name}' in '{spoken}'")
                return (display_name, fwd_number, person_id)

            # 2. Fuzzy word match — only for names 4+ chars (short names use exact only)
            name_nospace = name.replace(" ", "")
            if len(name_nospace) >= 4:
                for word in spoken_words:
                    if len(word) < 3:
                        continue
                    # Skip common words that cause false positives
                    if word in ("hello", "help", "here", "hear", "her", "him", "his",
                                "have", "how", "who", "hey", "the", "that", "this",
                                "they", "them", "there", "will", "with", "would"):
                        continue
                    # Character overlap ratio
                    matches = 0
                    j = 0
                    for c in name_nospace:
                        while j < len(word):
                            if word[j] == c:
                                matches += 1
                                j += 1
                                break
                            j += 1
                    if len(name_nospace) > 0:
                        ratio = matches / len(name_nospace)
                        if ratio >= 0.6 and abs(len(word) - len(name_nospace)) <= 2:
                            logger.info(f"Name fuzzy match: '{word}' ≈ '{name}' (ratio={ratio:.2f})")
                            return (display_name, fwd_number, person_id)

    return None

# Pre-built silence frame (20ms at 8kHz 16-bit mono = 320 bytes)
_SILENCE_PCM = b'\x00' * 320
_SILENCE_FRAME = AudioSocketProtocol.build_audio_frame(_SILENCE_PCM)

# Beep tone: 800Hz sine wave, 0.3 seconds, at 8kHz sample rate
def _generate_beep(freq=800, duration=0.3, volume=0.5):
    """Generate a short beep as 8kHz 16-bit PCM."""
    num_samples = int(ASTERISK_SAMPLE_RATE * duration)
    samples = []
    for i in range(num_samples):
        t = i / ASTERISK_SAMPLE_RATE
        # Fade in/out to avoid clicks (10ms ramp)
        ramp = min(i / 80, 1.0, (num_samples - i) / 80)
        val = int(volume * 32767 * ramp * math.sin(2 * math.pi * freq * t))
        samples.append(max(-32768, min(32767, val)))
    return struct.pack(f"<{len(samples)}h", *samples)

_BEEP_PCM = _generate_beep()

# Sentence boundary regex — split on . ! ? followed by space or end
_SENTENCE_RE = re.compile(r'(?<=[.!?])\s+|(?<=[.!?])$')


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
    """Synthesize text to 8kHz signed-linear PCM via Piper → sox pipe (no temp files)."""
    voice = get_config("ai.tts_voice", default="en_GB-alba-medium", db_path=db_path)
    model_path = f"{PIPER_MODEL_DIR}/{voice}.onnx"
    try:
        piper_cmd = [
            PIPER_BIN, "--model", model_path,
            "--output_raw", "--length_scale", "0.85",
        ]
        sox_cmd = [
            "sox", "-t", "raw", "-r", "22050", "-b", "16", "-e", "signed-integer", "-c", "1", "-L", "-",
            "-t", "raw", "-r", "8000", "-b", "16", "-e", "signed-integer", "-c", "1", "-L", "-",
        ]

        piper_proc = subprocess.Popen(
            piper_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        sox_proc = subprocess.Popen(
            sox_cmd, stdin=piper_proc.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        piper_proc.stdout.close()

        piper_proc.stdin.write(text.encode())
        piper_proc.stdin.close()

        pcm_data, sox_err = sox_proc.communicate(timeout=30)
        piper_proc.wait(timeout=5)

        if piper_proc.returncode != 0:
            stderr = piper_proc.stderr.read().decode()[:200]
            if "DiscoverDevicesForPlatform" not in stderr:
                logger.error(f"Piper failed (rc={piper_proc.returncode}): {stderr}")
                return b""

        if sox_proc.returncode != 0:
            logger.error(f"Sox failed: {sox_err.decode()[:200]}")
            return b""

        return pcm_data
    except Exception as e:
        logger.error(f"TTS error: {e}")
        return b""


def _stream_llm_sentences(llm_client, user_message, system_prompt, history):
    """Stream LLM and yield complete sentences as soon as they form.

    Instead of waiting for the full LLM response (5-10s), this yields
    each sentence as it completes (~1-2s for the first one).
    """
    buffer = ""
    for chunk in llm_client.chat_stream(user_message, system_prompt=system_prompt, history=history):
        buffer += chunk
        # Check for sentence boundaries
        parts = _SENTENCE_RE.split(buffer)
        if len(parts) > 1:
            # Yield all complete sentences, keep the incomplete remainder
            for sentence in parts[:-1]:
                sentence = sentence.strip()
                if sentence:
                    yield sentence
            buffer = parts[-1]
    # Yield any remaining text
    remainder = buffer.strip()
    if remainder:
        yield remainder


def _resolve_person_forward(response_text, persona_id, db_path=None, include_extension=False):
    """Check if the LLM response mentions connecting to a specific person.
    Returns forward_number (or (forward_number, internal_extension) if include_extension=True),
    or None to use the default."""
    if not persona_id:
        return None
    try:
        from db.connection import get_db_connection
        conn = get_db_connection(db_path)
        persons = conn.execute(
            "SELECT name, aliases, forward_number, internal_extension FROM persons WHERE persona_id = ? AND enabled = 1",
            (persona_id,),
        ).fetchall()
        conn.close()

        response_lower = response_text.lower()
        for person in persons:
            matched = False
            if person["name"].lower() in response_lower:
                matched = True
            if not matched and person["aliases"]:
                for alias in person["aliases"].split(","):
                    if alias.strip().lower() in response_lower:
                        matched = True
                        break
            if matched and (person["forward_number"] or person["internal_extension"]):
                ext = person["internal_extension"] or None
                fwd = person["forward_number"] or None
                logger.info(f"Person match: {person['name']} → fwd={fwd} ext={ext}")
                if include_extension:
                    return (fwd, ext)
                return fwd
    except Exception as e:
        logger.error(f"Person lookup failed: {e}")
    return None


async def _redirect_to_forward(db_path=None, forward_number=None, internal_extension=None):
    """Redirect the active inbound channel to the forward dialplan context.

    Finds the PJSIP/inbound-endpoint-* channel and sends it to forward,s,1.
    Sets FORWARD_TO (external number) and FORWARD_EXT (internal extension).
    The dialplan tries the extension first (10s), then falls back to external.
    """
    fwd = forward_number or get_config("sip.forward_number", db_path=db_path)
    if not fwd and not internal_extension:
        logger.warning("No forward number or extension configured")
        return

    try:
        result = subprocess.run(
            ["sudo", "/usr/sbin/asterisk", "-rx", "core show channels concise"],
            capture_output=True, timeout=5, text=True)
        channel_name = None
        for line in result.stdout.splitlines():
            if line.startswith("PJSIP/inbound-endpoint"):
                channel_name = line.split("!")[0]
                break
        if channel_name:
            ext_info = f" ext={internal_extension}" if internal_extension else ""
            logger.info(f"Redirecting {channel_name} → forward,s,1 (to {fwd}{ext_info})")

            # Set the external forward number
            if fwd:
                subprocess.run(
                    ["sudo", "/usr/sbin/asterisk", "-rx",
                     f"dialplan set chanvar {channel_name} FORWARD_TO {fwd}"],
                    capture_output=True, timeout=5)

            # Set the internal extension (if configured)
            if internal_extension:
                subprocess.run(
                    ["sudo", "/usr/sbin/asterisk", "-rx",
                     f"dialplan set chanvar {channel_name} FORWARD_EXT {internal_extension}"],
                    capture_output=True, timeout=5)

            subprocess.run(
                ["sudo", "/usr/sbin/asterisk", "-rx",
                 f"channel redirect {channel_name} forward,s,1"],
                capture_output=True, timeout=5)
        else:
            logger.warning(f"No inbound channel found. Output: {result.stdout[:200]} stderr: {result.stderr[:200]}")
    except Exception as e:
        logger.error(f"Forward redirect failed: {e}")


class AudioBridge:
    """Manages the AudioSocket write stream. Sends silence continuously,
    and can be interrupted to send TTS audio instead."""

    def __init__(self, writer: asyncio.StreamWriter):
        self.writer = writer
        self._playing = asyncio.Event()
        self._alive = True
        self._task = None

    async def start(self):
        self._task = asyncio.create_task(self._run())

    async def _run(self):
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

    async def play_beep(self):
        """Play a short beep tone to signal 'leave a message'."""
        await self.play_audio(_BEEP_PCM)

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

    async def stream_llm_and_speak(self, llm_client, user_message, system_prompt, history, db_path=None):
        """Stream LLM response sentence-by-sentence, synthesize and play each immediately.

        Uses a queue so LLM generation continues while TTS synthesizes/plays.
        First sentence arrives ~1-2s, gets spoken while the rest generates.
        """
        loop = asyncio.get_event_loop()
        queue = asyncio.Queue()
        full_response = ""

        def _produce_sentences():
            """Run in thread: stream LLM tokens, push sentences to queue."""
            try:
                for sentence in _stream_llm_sentences(llm_client, user_message, system_prompt, history):
                    asyncio.run_coroutine_threadsafe(queue.put(sentence), loop)
            except Exception as e:
                logger.error(f"LLM stream error: {e}")
            finally:
                asyncio.run_coroutine_threadsafe(queue.put(None), loop)  # sentinel

        # Start LLM streaming in background thread
        loop.run_in_executor(None, _produce_sentences)

        # Consume sentences: synthesize + play each as it arrives
        idx = 0
        while True:
            sentence = await queue.get()
            if sentence is None:
                break
            idx += 1
            full_response += (" " if full_response else "") + sentence
            logger.info(f"LLM sentence [{idx}]: '{sentence}'")

            audio = await loop.run_in_executor(None, _synthesize_tts_sync, sentence, db_path)
            if audio:
                await self.play_audio(audio)
                logger.info(f"TTS chunk [{idx}] played: {len(audio)} bytes ({len(audio)/(8000*2):.1f}s)")

        return full_response

    def stop(self):
        self._alive = False
        if self._task:
            self._task.cancel()


async def _play_cached_or_synth(bridge, text, db_path):
    """Play from phrase cache if available, otherwise synthesize live."""
    if text in _phrase_cache:
        logger.info(f"Playing cached: {text[:50]}...")
        await bridge.play_audio(_phrase_cache[text])
    else:
        await bridge.synthesize_and_play(text, db_path)


async def _play_greeting_cached(bridge, persona_id, session, db_path):
    """Play cached greeting or synthesize if not cached."""
    if persona_id and persona_id in _greeting_cache:
        logger.info(f"Playing cached greeting for persona {persona_id}")
        await bridge.play_audio(_greeting_cache[persona_id])
    else:
        await bridge.synthesize_and_play(session.get_greeting_text(), db_path)


async def handle_call(call_uuid, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Handle one phone call with streaming LLM→TTS pipeline."""
    db_path = DEFAULT_DB_PATH
    caller_number = "unknown"
    started_at = datetime.now()
    logger.info(f"Call started: {call_uuid}")

    # Get caller ID from Asterisk and dialed DID from temp file written by dialplan
    dialed_did = None
    try:
        # Read DID from temp file (written by extensions.conf System() before AudioSocket)
        did_file = f"/tmp/did_{call_uuid}"
        for _ in range(5):  # Retry briefly — file may not exist yet
            if os.path.exists(did_file):
                with open(did_file) as f:
                    did_val = f.read().strip()
                if did_val and did_val != "(None)" and did_val != "s":
                    dialed_did = did_val
                break
            await asyncio.sleep(0.1)

        # Get caller ID from Asterisk channel list
        result = subprocess.run(
            ["sudo", "/usr/sbin/asterisk", "-rx", "core show channels verbose"],
            capture_output=True, timeout=3, text=True)
        for line in result.stdout.splitlines():
            if "AudioSocket" in line:
                parts = line.split()
                for p in parts:
                    if len(p) >= 6 and p.replace("+", "").isdigit():
                        if caller_number == "unknown":
                            caller_number = p
                        break

        if caller_number != "unknown":
            logger.info(f"Caller ID: {caller_number}")
        if dialed_did:
            logger.info(f"Dialed DID: {dialed_did}")
        else:
            logger.warning(f"Could not determine dialed DID (file {did_file} not found or empty)")
    except Exception as e:
        logger.debug(f"Could not get call info: {e}")

    bridge = AudioBridge(writer)
    await bridge.start()

    session = None
    try:
        # Resolve persona by dialed DID (which number was called), not caller number
        persona = resolve_persona(dialed_did or caller_number, db_path)
        persona_id = persona["id"] if persona else None
        if persona and dialed_did:
            logger.info(f"Persona '{persona.get('name')}' matched for DID {dialed_did}")

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
            recognizer = vosk.KaldiRecognizer(_vosk_model, 16000)

        # Send greeting — use cached audio when available
        if session.vacation_active:
            await bridge.synthesize_and_play(session.vacation_message, db_path)
            await _play_cached_or_synth(bridge, "Would you like to leave a message?", db_path)
            await bridge.play_beep()
        elif session.outside_hours:
            company = persona.get("company_name") if persona else get_config("persona.company_name", "the company", db_path)
            start = get_config("availability.business_hours_start", "09:00", db_path)
            end = get_config("availability.business_hours_end", "17:00", db_path)
            await bridge.synthesize_and_play(
                f"Thank you for calling {company}. We are currently closed. "
                f"Our business hours are {start} to {end}, Monday to Friday.", db_path)
            await _play_cached_or_synth(bridge, "Please leave your name, number, and a brief message, and we'll get back to you.", db_path)
            await bridge.play_beep()
            session.system_prompt += "\nIMPORTANT: It is outside business hours. Take a message. Ask for name, number, and reason."
            logger.info("Outside business hours — taking messages")
        elif session.forced_unavailable:
            await _play_greeting_cached(bridge, persona_id, session, db_path)
            unavail = get_config("persona.unavailable_message", "They are not available right now.", db_path)
            await bridge.synthesize_and_play(unavail, db_path)
            await bridge.play_beep()
            session.system_prompt += "\nIMPORTANT: The person is unavailable. Take a message."
        else:
            await _play_greeting_cached(bridge, persona_id, session, db_path)

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

                # Handle silence from caller
                if not transcript:
                    session.silence_count += 1
                    if session.silence_count >= 3:
                        await bridge.synthesize_and_play("I haven't heard anything. Goodbye.", db_path)
                        break
                    await _play_cached_or_synth(bridge, "Are you still there?", db_path)
                    continue

                session.silence_count = 0

                # --- CODE WORD: bypass LLM entirely for instant response ---
                # Fuzzy match: Vosk often splits/mishears words.
                # "butterfly" heard as "author fly", "butter fly", "but her fly", etc.
                # Strategy: check if the transcript sounds close enough using
                # multiple matching methods.
                code_word = get_config("security.code_word", "", db_path)
                code_word_match = False
                if code_word:
                    cw = code_word.lower()
                    spoken = transcript.lower()
                    spoken_nospace = spoken.replace(" ", "")
                    cw_nospace = cw.replace(" ", "")
                    # 1. Exact substring match (with or without spaces)
                    code_word_match = cw in spoken or cw_nospace in spoken_nospace
                    # 2. Ending match — Vosk often garbles the start but gets the ending
                    #    "butterfly" ends with "fly", "author fly" ends with "fly"
                    if not code_word_match and len(cw) > 4:
                        suffix = cw_nospace[-3:]  # last 3 chars
                        code_word_match = spoken_nospace.endswith(suffix) and len(spoken_nospace) <= len(cw_nospace) + 4
                    # 3. Character overlap ratio — if 70%+ of chars match in order
                    if not code_word_match and len(cw_nospace) > 3:
                        matches = 0
                        j = 0
                        for c in cw_nospace:
                            while j < len(spoken_nospace):
                                if spoken_nospace[j] == c:
                                    matches += 1
                                    j += 1
                                    break
                                j += 1
                        ratio = matches / len(cw_nospace)
                        code_word_match = ratio >= 0.6 and len(spoken_nospace) <= len(cw_nospace) + 5
                    if code_word_match:
                        logger.info(f"Code word fuzzy match: '{spoken}' ≈ '{cw}'")
                if code_word_match:
                    logger.info(f"Code word detected! Forwarding call.")
                    session.transcript.append({"role": "user", "text": transcript})
                    await bridge.synthesize_and_play("Connecting you now.", db_path)
                    session.action_taken = "forwarded"
                    session.transcript.append({"role": "assistant", "text": "Connecting you now."})
                    # Redirect the Asterisk channel to the forward context
                    await _redirect_to_forward(db_path)
                    break

                # --- PERSON NAME DETECTION: skip LLM, check availability, forward ---
                person_match = _match_person_in_transcript(transcript, persona_id)
                if person_match:
                    display_name, fwd_number, matched_person_id = person_match
                    logger.info(f"Person name detected in STT: '{display_name}' → {fwd_number}")
                    session.transcript.append({"role": "user", "text": transcript})

                    # Check availability before forwarding
                    from engine.tools import _handle_check_availability
                    from db.connection import get_db_connection
                    conn = get_db_connection(db_path)
                    person_row = conn.execute("SELECT * FROM persons WHERE id = ?", (matched_person_id,)).fetchone()
                    conn.close()
                    person_dict = dict(person_row) if person_row else None

                    avail = _handle_check_availability({}, db_path=db_path, person=person_dict)
                    logger.info(f"Availability for {display_name}: {avail}")

                    if avail.get("action") == "forward":
                        phrase = f"Connecting you to {display_name} now."
                        await _play_cached_or_synth(bridge, phrase, db_path)
                        session.action_taken = "forwarded"
                        session.transcript.append({"role": "assistant", "text": phrase})
                        int_ext = person_dict.get("internal_extension") if person_dict else None
                        await _redirect_to_forward(db_path, forward_number=fwd_number, internal_extension=int_ext)
                        break
                    else:
                        # Person is unavailable — take a message
                        status = avail.get("status", "unavailable")
                        logger.info(f"{display_name} is {status} — taking message")
                        phrase = f"I'm sorry, {display_name} is not available at the moment. Would you like to leave a message?"
                        await bridge.synthesize_and_play(phrase, db_path)
                        session.transcript.append({"role": "assistant", "text": phrase})
                        # Continue the loop — LLM handles the message-taking conversation

                session.transcript.append({"role": "user", "text": transcript})

                # Build LLM history
                history = [
                    {"role": "user" if t["role"] == "user" else "assistant", "content": t["text"]}
                    for t in session.transcript[:-1]
                ]

                # STREAMING: speak each sentence as it's generated
                t0 = datetime.now()
                response_text = await bridge.stream_llm_and_speak(
                    session.llm, transcript, session.system_prompt, history, db_path
                )
                elapsed = (datetime.now() - t0).total_seconds()
                logger.info(f"Turn [{turn_count}] total: {elapsed:.1f}s response='{response_text[:80]}'")

                session.transcript.append({"role": "assistant", "text": response_text})

                # Check for call-ending keywords in the response
                lower = response_text.lower()
                if "goodbye" in lower or "good bye" in lower:
                    session.state = "ending"
                    break
                if "connecting you" in lower or "connected" in lower or "transfer" in lower or "forwarding" in lower or "put you through" in lower:
                    session.action_taken = "forwarded"
                    result = _resolve_person_forward(lower, persona_id, db_path, include_extension=True)
                    fwd_number, int_ext = result if result else (None, None)
                    await _redirect_to_forward(db_path, forward_number=fwd_number, internal_extension=int_ext)
                    break

                # Also check if the caller asked for a team member by name
                if persona_id:
                    result = _resolve_person_forward(transcript.lower(), persona_id, db_path, include_extension=True)
                    if result:
                        fwd_number, int_ext = result
                        if fwd_number or int_ext:
                            if "check" in lower or "available" in lower or "let me" in lower:
                                session.action_taken = "forwarded"
                                await bridge.synthesize_and_play(f"Let me connect you now.", db_path)
                                await _redirect_to_forward(db_path, forward_number=fwd_number, internal_extension=int_ext)
                                break

            if len(audio_buffer) > ASTERISK_SAMPLE_RATE * ASTERISK_SAMPLE_WIDTH * 30:
                audio_buffer.clear()
                speech_frames = 0

    except Exception as e:
        logger.error(f"Call {call_uuid} error: {e}", exc_info=True)
    finally:
        bridge.stop()

        duration = int((datetime.now() - started_at).total_seconds())
        summary = session.end_call(reason="completed") if session else {"action_taken": "error"}

        # Format transcript as readable text for email
        transcript_lines = []
        for entry in summary.get("transcript", []):
            role = "Caller" if entry.get("role") == "user" else "AI"
            transcript_lines.append(f"{role}: {entry.get('text', '')}")
        formatted_transcript = "\n".join(transcript_lines) or "(no conversation)"

        # Extract caller name and reason from transcript if not already set
        caller_name = summary.get("caller_name", "Unknown")
        reason = summary.get("reason", "")
        if caller_name == "Unknown" and transcript_lines:
            # Simple extraction: look for "my name is X" or "this is X" in caller's first turns
            for entry in summary.get("transcript", []):
                if entry.get("role") == "user":
                    text = entry.get("text", "").lower()
                    for prefix in ["my name is ", "this is ", "i'm ", "i am "]:
                        if prefix in text:
                            idx = text.index(prefix) + len(prefix)
                            name_part = entry["text"][idx:].split(",")[0].split(".")[0].split(" and ")[0].strip()
                            # Take up to 3 words as name
                            words = name_part.split()[:3]
                            if words:
                                caller_name = " ".join(w.capitalize() for w in words)
                                break
                    if caller_name != "Unknown":
                        break

        # Build persona context for email
        persona_name = persona.get("company_name", "Unknown") if persona else "Unknown"
        did_display = dialed_did or "Unknown"

        try:
            call_id = log_call(
                db_path=db_path, caller_number=caller_number,
                caller_name=caller_name,
                reason=reason or summary.get("action_taken", "ended"),
                transcript=summary.get("transcript", []),
                action_taken=summary.get("action_taken", "ended"),
                duration_seconds=duration,
            )
            process_post_call_actions(
                db_path=db_path, call_id=call_id,
                caller_name=caller_name,
                caller_number=caller_number,
                reason=reason or summary.get("action_taken", "ended"),
                transcript=formatted_transcript,
                action_taken=summary.get("action_taken", "ended"),
                persona_name=persona_name,
                dialed_did=did_display,
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
