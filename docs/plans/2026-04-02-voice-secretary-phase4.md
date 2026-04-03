# Voice Secretary Phase 4: Orchestrator + Call Flow + Polish

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire everything together into a working call flow: Asterisk receives call → AudioSocket streams audio → orchestrator runs STT → LLM (with tool calling) → TTS → audio back to caller. Forward calls cascade through internal extensions first, then SIP trunk, then fall back to AI message-taking. Add TTS caching, WebSocket live call status, and Asterisk config apply button.

**Architecture:** The orchestrator is an async Python server listening on TCP port 9092 for Asterisk AudioSocket connections. Each call spawns a `CallSession` that manages the STT→LLM→TTS pipeline, conversation history, tool call execution, and call state transitions. Internal SIP extensions are configured via a new dashboard section. Forwarding uses cascading Dial with timeout.

**Tech Stack:** Python asyncio (AudioSocket server), Asterisk AudioSocket protocol, Ollama (tool calling), Vosk (streaming STT), Piper (TTS), Flask-SocketIO (real-time dashboard updates)

**Design reference:** `/Users/harrowiersma/Documents/CLAUDE/assistant/develop.md`

**Phase 3 codebase:** 97 tests passing, engine wrappers + all dashboard screens + MS Graph + email + tools

---

### Task 1: TTS Cache (Pre-render Static Messages to WAV)

**Files:**
- Create: `voice-secretary/engine/tts_cache.py`
- Test: `voice-secretary/tests/test_tts_cache.py`

**Step 1: Write the failing test**

```python
# tests/test_tts_cache.py
import tempfile
import os
import pytest
from db.init_db import init_db
from db.connection import get_db_connection
from app.helpers import set_config


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    os.unlink(path)


@pytest.fixture
def cache_dir():
    d = tempfile.mkdtemp()
    yield d
    import shutil
    shutil.rmtree(d)


def test_cache_greeting_creates_file(db_path, cache_dir):
    from engine.tts_cache import TTSCache
    set_config("persona.greeting", "Hello, welcome to TestCo.", "persona", db_path)
    cache = TTSCache(db_path=db_path, cache_dir=cache_dir, tts_available=False)
    path = cache.cache_greeting()
    # When TTS not available, returns None but doesn't crash
    assert path is None


def test_cache_greeting_with_mock_tts(db_path, cache_dir):
    from engine.tts_cache import TTSCache
    set_config("persona.greeting", "Hello, welcome to TestCo.", "persona", db_path)
    set_config("persona.company_name", "TestCo", "persona", db_path)
    cache = TTSCache(db_path=db_path, cache_dir=cache_dir, tts_available=False)
    # Simulate a cached file
    fake_path = os.path.join(cache_dir, "greeting.wav")
    with open(fake_path, "wb") as f:
        f.write(b"RIFF fake wav data")
    path = cache.get_greeting_path()
    assert path == fake_path


def test_cache_vacation_message(db_path, cache_dir):
    from engine.tts_cache import TTSCache
    conn = get_db_connection(db_path)
    conn.execute(
        "INSERT INTO knowledge_rules (rule_type, response, active_from, active_until, enabled) "
        "VALUES ('vacation', 'We are closed for holidays.', date('now','-1 day'), date('now','+1 day'), 1)"
    )
    conn.commit()
    conn.close()
    cache = TTSCache(db_path=db_path, cache_dir=cache_dir, tts_available=False)
    path = cache.cache_vacation_message()
    assert path is None  # TTS not available, graceful


def test_empty_greeting_no_crash(db_path, cache_dir):
    from engine.tts_cache import TTSCache
    set_config("persona.greeting", "", "persona", db_path)
    cache = TTSCache(db_path=db_path, cache_dir=cache_dir, tts_available=False)
    path = cache.cache_greeting()
    assert path is None
```

**Step 2: Run test to verify it fails**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_tts_cache.py -v`
Expected: FAIL (module doesn't exist)

**Step 3: Implement TTS cache**

```python
# engine/tts_cache.py
import os
import hashlib
import logging
from app.helpers import get_config
from engine.prompt_builder import get_active_vacation

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "instance", "tts_cache"
)


class TTSCache:
    """Pre-renders static messages to WAV files for fast playback during calls."""

    def __init__(self, db_path=None, cache_dir=None, tts_available=None):
        self.db_path = db_path
        self.cache_dir = cache_dir or DEFAULT_CACHE_DIR
        os.makedirs(self.cache_dir, exist_ok=True)

        if tts_available is not None:
            self._tts_available = tts_available
        else:
            from engine.tts import TTSEngine
            self._tts_available = TTSEngine().is_available()

    def _text_hash(self, text):
        return hashlib.md5(text.encode()).hexdigest()[:12]

    def _render_to_file(self, text, filename):
        """Render text to WAV via Piper. Returns file path or None."""
        if not text or not self._tts_available:
            return None
        try:
            from engine.tts import TTSEngine
            engine = TTSEngine()
            audio_bytes = engine.synthesize(text)
            if audio_bytes:
                path = os.path.join(self.cache_dir, filename)
                with open(path, "wb") as f:
                    f.write(audio_bytes)
                logger.info(f"Cached TTS: {filename} ({len(audio_bytes)} bytes)")
                return path
        except Exception as e:
            logger.error(f"TTS cache render failed: {e}")
        return None

    def cache_greeting(self):
        """Pre-render the greeting message. Returns path or None."""
        greeting = get_config("persona.greeting", default="", db_path=self.db_path)
        company = get_config("persona.company_name", default="", db_path=self.db_path)
        if not greeting:
            return None
        text = greeting.replace("{company}", company)
        return self._render_to_file(text, "greeting.wav")

    def cache_vacation_message(self):
        """Pre-render active vacation message. Returns path or None."""
        vacation = get_active_vacation(self.db_path)
        if not vacation:
            return None
        return self._render_to_file(vacation["response"], f"vacation_{vacation['id']}.wav")

    def get_greeting_path(self):
        """Get path to cached greeting WAV if it exists."""
        path = os.path.join(self.cache_dir, "greeting.wav")
        return path if os.path.exists(path) else None

    def get_vacation_path(self):
        """Get path to cached vacation WAV if it exists."""
        vacation = get_active_vacation(self.db_path)
        if not vacation:
            return None
        path = os.path.join(self.cache_dir, f"vacation_{vacation['id']}.wav")
        return path if os.path.exists(path) else None
```

**Step 4: Run test to verify it passes**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_tts_cache.py -v`
Expected: 4 PASSED

**Step 5: Commit**

```bash
git add engine/tts_cache.py tests/test_tts_cache.py
git commit -m "feat: TTS cache for pre-rendering greeting and vacation messages to WAV"
```

---

### Task 2: LLM Client Tool Calling Support

**Files:**
- Modify: `voice-secretary/engine/llm.py`
- Test: `voice-secretary/tests/test_llm_tools.py`

**Step 1: Write the failing test**

```python
# tests/test_llm_tools.py
import json
from unittest.mock import patch, MagicMock
import pytest
from engine.llm import LLMClient
from engine.tools import TOOL_DEFINITIONS


def test_chat_with_tools_sends_tools_in_request():
    client = LLMClient(model="llama3.2:1b")
    client._available = True  # Force available

    captured_data = {}

    def mock_urlopen(req, timeout=None):
        captured_data["body"] = json.loads(req.data)
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({
            "message": {"role": "assistant", "content": "I'll check that for you."}
        }).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        client.chat("Is Harro available?", system_prompt="You are a secretary.", tools=TOOL_DEFINITIONS)

    assert "tools" in captured_data["body"]
    assert len(captured_data["body"]["tools"]) == len(TOOL_DEFINITIONS)


def test_chat_returns_tool_call_when_llm_requests_it():
    client = LLMClient(model="llama3.2:1b")
    client._available = True

    def mock_urlopen(req, timeout=None):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "function": {
                        "name": "check_availability",
                        "arguments": {}
                    }
                }]
            }
        }).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        result = client.chat("Is Harro available?", system_prompt="You are a secretary.", tools=TOOL_DEFINITIONS)

    assert isinstance(result, dict)
    assert "tool_calls" in result


def test_chat_without_tools_returns_string():
    client = LLMClient(model="llama3.2:1b")
    client._available = True

    def mock_urlopen(req, timeout=None):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({
            "message": {"role": "assistant", "content": "Hello! How can I help?"}
        }).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        result = client.chat("Hello", system_prompt="Test")

    assert isinstance(result, str)
    assert "Hello" in result
```

**Step 2: Run test to verify it fails**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_llm_tools.py -v`
Expected: FAIL (chat doesn't accept tools param)

**Step 3: Update LLM client to support tool calling**

Update `engine/llm.py` — modify the `chat` method to:
- Accept optional `tools` parameter
- Include tools in the Ollama request body when provided
- When response contains `tool_calls`, return the full message dict (not just content string)
- When response has no tool_calls, return content string as before

```python
def chat(self, user_message, system_prompt="", history=None, tools=None):
    if not self.is_available():
        logger.warning("Ollama not available, returning fallback")
        return FALLBACK_RESPONSE
    try:
        import urllib.request
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        body = {"model": self.model, "messages": messages, "stream": False}
        if tools:
            body["tools"] = tools

        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{self.base_url}/api/chat", data=data,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            message = result["message"]
            # If LLM requested tool calls, return full message dict
            if message.get("tool_calls"):
                return message
            return message["content"]
    except Exception as e:
        logger.error(f"LLM chat error: {e}")
        return FALLBACK_RESPONSE
```

**Step 4: Run test to verify it passes**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_llm_tools.py -v`
Expected: 3 PASSED

**Step 5: Run ALL tests**

Run: `cd voice-secretary && .venv/bin/pytest tests/ -v`
Expected: ALL PASSED (existing tests unbroken since tools param is optional)

**Step 6: Commit**

```bash
git add engine/llm.py tests/test_llm_tools.py
git commit -m "feat: LLM client tool calling support for Ollama"
```

---

### Task 3: Call Session (Orchestrator Core Logic)

**Files:**
- Create: `voice-secretary/engine/call_session.py`
- Test: `voice-secretary/tests/test_call_session.py`

This is the core brain — a `CallSession` class that manages one phone call's conversation flow. It's tested entirely with mocks (no real audio, SIP, or AI needed).

**Step 1: Write the failing test**

```python
# tests/test_call_session.py
import tempfile
import os
import json
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, timedelta
import pytest
from db.init_db import init_db
from db.connection import get_db_connection
from app.helpers import set_config


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    # Seed persona
    set_config("persona.company_name", "TestCo", "persona", path)
    set_config("persona.greeting", "Hello, you've reached {company}.", "persona", path)
    set_config("persona.personality", "Professional and friendly.", "persona", path)
    set_config("persona.unavailable_message", "They are not available.", "persona", path)
    # Seed availability
    set_config("availability.manual_override", "auto", "availability", path)
    set_config("sip.forward_number", "+41791234567", "sip", path)
    yield path
    os.unlink(path)


def test_call_session_creates(db_path):
    from engine.call_session import CallSession
    session = CallSession(
        caller_number="+41791111111",
        db_path=db_path,
    )
    assert session.caller_number == "+41791111111"
    assert session.state == "greeting"
    assert session.transcript == []


def test_call_session_greeting(db_path):
    from engine.call_session import CallSession
    session = CallSession(caller_number="+41791111111", db_path=db_path)
    greeting = session.get_greeting_text()
    assert "TestCo" in greeting


def test_call_session_process_turn_returns_response(db_path):
    from engine.call_session import CallSession
    session = CallSession(caller_number="+41791111111", db_path=db_path)

    # Mock LLM to return a simple text response
    mock_llm = MagicMock()
    mock_llm.chat.return_value = "Sure, let me check if they're available."
    session.llm = mock_llm

    response = session.process_turn("Hi, I'd like to speak to Harro.")
    assert isinstance(response, str)
    assert len(response) > 0
    assert len(session.transcript) == 2  # user + assistant


def test_call_session_handles_tool_call(db_path):
    from engine.call_session import CallSession
    session = CallSession(caller_number="+41791111111", db_path=db_path)

    # Mock LLM: first call returns tool_call, second returns text
    tool_response = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": "check_availability", "arguments": {}}}],
    }
    mock_llm = MagicMock()
    mock_llm.chat.side_effect = [tool_response, "They're available! Let me transfer you now."]
    session.llm = mock_llm

    response = session.process_turn("Is Harro available?", mock_presence="available")
    assert isinstance(response, str)
    assert len(response) > 0


def test_call_session_vacation_detected(db_path):
    from engine.call_session import CallSession
    conn = get_db_connection(db_path)
    conn.execute(
        "INSERT INTO knowledge_rules (rule_type, response, active_from, active_until, enabled) "
        "VALUES ('vacation', 'We are closed for the holidays.', date('now','-1 day'), date('now','+1 day'), 1)"
    )
    conn.commit()
    conn.close()
    session = CallSession(caller_number="+41791111111", db_path=db_path)
    assert session.vacation_active is True
    assert "holidays" in session.vacation_message


def test_call_session_forward_action(db_path):
    from engine.call_session import CallSession
    session = CallSession(caller_number="+41791111111", db_path=db_path)

    # Simulate forward tool call result
    action = session.handle_action({"action": "forward", "number": "+41791234567"})
    assert action["type"] == "forward"
    assert action["number"] == "+41791234567"


def test_call_session_end_call(db_path):
    from engine.call_session import CallSession
    session = CallSession(caller_number="+41791111111", db_path=db_path)
    session.transcript = [
        {"role": "caller", "text": "Hello"},
        {"role": "assistant", "text": "Hi there"},
    ]
    result = session.end_call(reason="caller_goodbye")
    assert result["action_taken"] in ("forwarded", "message_taken", "ended")
    assert result["duration_seconds"] >= 0


def test_call_session_manual_override_unavailable(db_path):
    set_config("availability.manual_override", "unavailable", "availability", db_path)
    from engine.call_session import CallSession
    session = CallSession(caller_number="+41791111111", db_path=db_path)
    assert session.forced_unavailable is True


def test_call_session_silence_handling(db_path):
    from engine.call_session import CallSession
    session = CallSession(caller_number="+41791111111", db_path=db_path)
    mock_llm = MagicMock()
    mock_llm.chat.return_value = "Are you still there?"
    session.llm = mock_llm

    # Empty STT result
    response = session.process_turn("")
    assert session.silence_count == 1
    assert "still there" in response.lower()
```

**Step 2: Run test to verify it fails**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_call_session.py -v`
Expected: FAIL

**Step 3: Implement CallSession**

```python
# engine/call_session.py
import json
import logging
from datetime import datetime
from engine.prompt_builder import build_system_prompt, get_active_vacation
from engine.tools import TOOL_DEFINITIONS, execute_tool
from engine.llm import LLMClient
from app.helpers import get_config

logger = logging.getLogger(__name__)

MAX_SILENCE_RETRIES = 3


class CallSession:
    """Manages one phone call's conversation flow."""

    def __init__(self, caller_number, db_path=None):
        self.caller_number = caller_number
        self.db_path = db_path
        self.state = "greeting"  # greeting, conversation, forwarding, ending
        self.transcript = []
        self.started_at = datetime.now()
        self.silence_count = 0
        self.caller_name = None
        self.reason = None
        self.action_taken = None

        # Load config
        self.system_prompt = build_system_prompt(db_path)
        model = get_config("ai.llm_model", default="llama3.2:1b", db_path=db_path)
        self.llm = LLMClient(model=model)

        # Check vacation
        vacation = get_active_vacation(db_path)
        self.vacation_active = vacation is not None
        self.vacation_message = vacation["response"] if vacation else None

        # Check manual override
        override = get_config("availability.manual_override", default="auto", db_path=db_path)
        self.forced_unavailable = (override == "unavailable")
        self.forced_available = (override == "available")

    def get_greeting_text(self):
        """Get the greeting message with company name substituted."""
        greeting = get_config("persona.greeting", default="Hello.", db_path=self.db_path)
        company = get_config("persona.company_name", default="", db_path=self.db_path)
        return greeting.replace("{company}", company)

    def process_turn(self, caller_text, mock_presence=None):
        """Process one conversation turn. Returns AI response text."""
        # Handle silence
        if not caller_text.strip():
            self.silence_count += 1
            if self.silence_count >= MAX_SILENCE_RETRIES:
                self.state = "ending"
                return "I haven't heard anything. I'll hang up now. Goodbye."
            return "Are you still there? I didn't catch that."

        self.silence_count = 0
        self.transcript.append({"role": "user", "text": caller_text})

        # Build history for LLM
        history = [
            {"role": "user" if t["role"] == "user" else "assistant", "content": t["text"]}
            for t in self.transcript[:-1]  # Exclude current message (added in chat call)
        ]

        # Call LLM with tools
        result = self.llm.chat(
            user_message=caller_text,
            system_prompt=self.system_prompt,
            history=history,
            tools=TOOL_DEFINITIONS,
        )

        # Handle tool calls
        if isinstance(result, dict) and result.get("tool_calls"):
            tool_results = []
            for tool_call in result["tool_calls"]:
                func = tool_call["function"]
                tool_result = execute_tool(
                    func["name"],
                    func.get("arguments", {}),
                    db_path=self.db_path,
                    mock_presence=mock_presence,
                )
                tool_results.append(tool_result)

                # Handle forward/end actions
                if tool_result.get("action") == "forward":
                    self.action_taken = "forwarded"
                elif tool_result.get("action") == "hangup":
                    self.state = "ending"
                elif tool_result.get("success") and func["name"] == "take_message":
                    self.caller_name = tool_result.get("caller_name")
                    self.reason = tool_result.get("reason")
                    self.action_taken = "message_taken"

            # Feed tool results back to LLM for natural response
            tool_context = json.dumps(tool_results)
            history.append({"role": "user", "content": caller_text})
            history.append({"role": "assistant", "content": f"[Tool results: {tool_context}]"})
            response_text = self.llm.chat(
                user_message=f"Based on these tool results, respond naturally to the caller: {tool_context}",
                system_prompt=self.system_prompt,
                history=history,
            )
        else:
            response_text = result if isinstance(result, str) else str(result)

        self.transcript.append({"role": "assistant", "text": response_text})
        return response_text

    def handle_action(self, tool_result):
        """Handle a tool action result (forward, hangup, etc.)."""
        action = tool_result.get("action")
        if action == "forward":
            self.state = "forwarding"
            self.action_taken = "forwarded"
            return {"type": "forward", "number": tool_result.get("number")}
        elif action == "hangup":
            self.state = "ending"
            return {"type": "hangup"}
        return {"type": "continue"}

    def end_call(self, reason="ended"):
        """Finalize the call session and return summary."""
        self.state = "ending"
        duration = int((datetime.now() - self.started_at).total_seconds())
        return {
            "caller_number": self.caller_number,
            "caller_name": self.caller_name or "Unknown",
            "reason": self.reason or reason,
            "transcript": self.transcript,
            "action_taken": self.action_taken or "ended",
            "duration_seconds": duration,
        }
```

**Step 4: Run test to verify it passes**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_call_session.py -v`
Expected: 9 PASSED

**Step 5: Commit**

```bash
git add engine/call_session.py tests/test_call_session.py
git commit -m "feat: CallSession manages conversation flow with tool calling and state transitions"
```

---

### Task 4: AudioSocket Server (Orchestrator Network Layer)

**Files:**
- Create: `voice-secretary/engine/audiosocket.py`
- Create: `voice-secretary/engine/__main__.py`
- Test: `voice-secretary/tests/test_audiosocket.py`

**Step 1: Write the failing test**

```python
# tests/test_audiosocket.py
import asyncio
import struct
import pytest
from engine.audiosocket import AudioSocketProtocol, AUDIO_TYPE, UUID_TYPE, HANGUP_TYPE


def test_parse_uuid_frame():
    """AudioSocket protocol: first frame is UUID identifying the call."""
    uuid_bytes = b"\x01" * 16
    frame = struct.pack("!BH", UUID_TYPE, 16) + uuid_bytes
    msg_type, payload = AudioSocketProtocol.parse_frame(frame)
    assert msg_type == UUID_TYPE
    assert payload == uuid_bytes


def test_parse_audio_frame():
    """AudioSocket protocol: audio frames contain PCM data."""
    audio_data = b"\x00\x01" * 160  # 320 bytes = 20ms at 16kHz 16-bit
    frame = struct.pack("!BH", AUDIO_TYPE, len(audio_data)) + audio_data
    msg_type, payload = AudioSocketProtocol.parse_frame(frame)
    assert msg_type == AUDIO_TYPE
    assert payload == audio_data


def test_parse_hangup_frame():
    """AudioSocket protocol: hangup frame signals call end."""
    frame = struct.pack("!BH", HANGUP_TYPE, 0)
    msg_type, payload = AudioSocketProtocol.parse_frame(frame)
    assert msg_type == HANGUP_TYPE


def test_build_audio_frame():
    """Build an audio frame to send back to Asterisk."""
    audio_data = b"\x00\x01" * 80
    frame = AudioSocketProtocol.build_audio_frame(audio_data)
    assert len(frame) == 3 + len(audio_data)
    msg_type = frame[0]
    length = struct.unpack("!H", frame[1:3])[0]
    assert msg_type == AUDIO_TYPE
    assert length == len(audio_data)
```

**Step 2: Run test to verify it fails**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_audiosocket.py -v`
Expected: FAIL

**Step 3: Implement AudioSocket protocol and server**

```python
# engine/audiosocket.py
"""
Asterisk AudioSocket protocol implementation.

AudioSocket is a simple TCP protocol:
- Frame format: 1 byte type + 2 bytes length (big-endian) + payload
- Types: 0x00 = hangup, 0x01 = UUID, 0x10 = audio (16-bit signed LE, 8kHz mono)
- Asterisk sends UUID frame first, then streams audio frames
- We send audio frames back for TTS playback
"""
import asyncio
import struct
import logging
import uuid as uuid_mod

logger = logging.getLogger(__name__)

HANGUP_TYPE = 0x00
UUID_TYPE = 0x01
AUDIO_TYPE = 0x10

LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 9092


class AudioSocketProtocol:
    """Parse and build AudioSocket protocol frames."""

    @staticmethod
    def parse_frame(data):
        """Parse a single AudioSocket frame. Returns (type, payload)."""
        if len(data) < 3:
            return None, None
        msg_type = data[0]
        length = struct.unpack("!H", data[1:3])[0]
        payload = data[3:3 + length] if length > 0 else b""
        return msg_type, payload

    @staticmethod
    def build_audio_frame(audio_data):
        """Build an audio frame to send to Asterisk."""
        header = struct.pack("!BH", AUDIO_TYPE, len(audio_data))
        return header + audio_data

    @staticmethod
    def build_hangup_frame():
        """Build a hangup frame."""
        return struct.pack("!BH", HANGUP_TYPE, 0)


async def read_frame(reader):
    """Read one complete AudioSocket frame from the stream."""
    header = await reader.readexactly(3)
    msg_type = header[0]
    length = struct.unpack("!H", header[1:3])[0]
    payload = await reader.readexactly(length) if length > 0 else b""
    return msg_type, payload


async def handle_call(reader, writer, call_handler=None):
    """Handle one AudioSocket connection (one phone call)."""
    call_uuid = None
    addr = writer.get_extra_info("peername")
    logger.info(f"AudioSocket connection from {addr}")

    try:
        # First frame should be UUID
        msg_type, payload = await read_frame(reader)
        if msg_type == UUID_TYPE:
            call_uuid = uuid_mod.UUID(bytes=payload)
            logger.info(f"Call UUID: {call_uuid}")

        # Hand off to call handler if provided
        if call_handler:
            await call_handler(reader, writer, call_uuid)
        else:
            # Default: echo loop for testing
            while True:
                msg_type, payload = await read_frame(reader)
                if msg_type == HANGUP_TYPE:
                    logger.info(f"Call {call_uuid} hung up")
                    break
                elif msg_type == AUDIO_TYPE:
                    # Echo audio back (for testing)
                    frame = AudioSocketProtocol.build_audio_frame(payload)
                    writer.write(frame)
                    await writer.drain()
    except asyncio.IncompleteReadError:
        logger.info(f"Call {call_uuid} disconnected")
    except Exception as e:
        logger.error(f"Call {call_uuid} error: {e}")
    finally:
        writer.close()
        logger.info(f"Call {call_uuid} session ended")


async def start_server(host=LISTEN_HOST, port=LISTEN_PORT, call_handler=None):
    """Start the AudioSocket TCP server."""
    server = await asyncio.start_server(
        lambda r, w: handle_call(r, w, call_handler),
        host, port,
    )
    logger.info(f"AudioSocket server listening on {host}:{port}")
    return server
```

```python
# engine/__main__.py
"""Entry point for the voice secretary engine."""
import asyncio
import logging
from engine.audiosocket import start_server

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def main():
    server = await start_server()
    async with server:
        logger.info("Voice Secretary Engine running. Waiting for calls...")
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
```

**Step 4: Run test to verify it passes**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_audiosocket.py -v`
Expected: 4 PASSED

**Step 5: Commit**

```bash
git add engine/audiosocket.py engine/__main__.py tests/test_audiosocket.py
git commit -m "feat: AudioSocket protocol parser and TCP server for Asterisk integration"
```

---

### Task 5: Internal SIP Extensions Support

**Files:**
- Modify: `voice-secretary/config/asterisk/pjsip.conf.j2` (add extension registration)
- Modify: `voice-secretary/config/asterisk/extensions.conf.j2` (cascading forward)
- Modify: `voice-secretary/config/defaults.py` (add extension defaults)
- Modify: `voice-secretary/app/routes/sip.py` (add extensions section)
- Modify: `voice-secretary/app/templates/sip.html` (add extensions form)
- Test: `voice-secretary/tests/test_sip.py` (extend)

**Step 1: Write the additional failing test**

Add to `tests/test_sip.py`:

```python
def test_sip_page_has_extensions_section(client):
    response = client.get("/sip")
    html = response.data.decode()
    assert 'name="sip.extension_1_name"' in html
    assert 'name="sip.extension_1_password"' in html


def test_sip_save_with_extension(client):
    response = client.post("/sip/save", data={
        "sip.inbound_server": "sip.example.com",
        "sip.inbound_username": "user123",
        "sip.inbound_password": "pass456",
        "sip.inbound_port": "5060",
        "sip.forward_number": "+41791234567",
        "sip.extension_1_name": "desk-phone",
        "sip.extension_1_password": "ext-pass-1",
        "sip.extension_2_name": "",
        "sip.extension_2_password": "",
    }, follow_redirects=True)
    assert response.status_code == 200


def test_asterisk_config_with_extension(client):
    from config.asterisk_gen import render_pjsip_conf, render_extensions_conf
    config = {
        "sip.inbound_server": "sip.example.com",
        "sip.inbound_username": "user123",
        "sip.inbound_password": "pass456",
        "sip.inbound_port": "5060",
        "sip.forward_number": "+41791234567",
        "sip.extension_1_name": "desk-phone",
        "sip.extension_1_password": "ext-pass-1",
    }
    pjsip = render_pjsip_conf(config)
    assert "desk-phone" in pjsip

    extensions = render_extensions_conf(config)
    # Cascading dial: extension first, then SIP trunk
    assert "desk-phone" in extensions
    assert "+41791234567" in extensions
```

**Step 2: Run test to verify it fails**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_sip.py -v`
Expected: 3 new tests FAIL

**Step 3: Update SIP config for internal extensions**

Add extension fields to SIP_FIELDS and SIP_DEFAULTS in `config/defaults.py`:
```python
# Add to SIP_DEFAULTS:
"sip.extension_1_name": "",
"sip.extension_1_password": "",
"sip.extension_2_name": "",
"sip.extension_2_password": "",
"sip.extension_3_name": "",
"sip.extension_3_password": "",
```

Add to SIP_FIELDS in `app/routes/sip.py`:
```python
"sip.extension_1_name", "sip.extension_1_password",
"sip.extension_2_name", "sip.extension_2_password",
"sip.extension_3_name", "sip.extension_3_password",
```

Update `app/templates/sip.html` — add after the outbound section:
```html
<h3>Internal Extensions</h3>
<p class="help-text">Register SIP phones on your local network. Calls forward to extensions first (free), then to your mobile via SIP trunk.</p>
{% for i in range(1, 4) %}
<div class="grid">
    <label>
        Extension {{ i }} Name
        <input type="text" name="sip.extension_{{ i }}_name" value="{{ values['sip.extension_' ~ i ~ '_name'] }}" placeholder="desk-phone">
    </label>
    <label>
        Extension {{ i }} Password
        <input type="password" name="sip.extension_{{ i }}_password" value="{{ values['sip.extension_' ~ i ~ '_password'] }}">
    </label>
</div>
{% endfor %}
```

Update `config/asterisk/pjsip.conf.j2` — add extension endpoints:
```jinja2
{% for i in range(1, 4) %}
{% set ext_name = 'sip_extension_' ~ i ~ '_name' %}
{% set ext_pass = 'sip_extension_' ~ i ~ '_password' %}
{% if vars().get(ext_name) or (ext_name in _context and _context[ext_name]) %}
; === Internal Extension {{ i }}: {{ vars().get(ext_name, '') }} ===
[{{ vars().get(ext_name, 'ext' ~ i) }}]
type=endpoint
transport=transport-udp
context=internal
disallow=all
allow=ulaw
allow=alaw
auth={{ vars().get(ext_name, 'ext' ~ i) }}-auth
aors={{ vars().get(ext_name, 'ext' ~ i) }}-aor

[{{ vars().get(ext_name, 'ext' ~ i) }}-auth]
type=auth
auth_type=userpass
username={{ vars().get(ext_name, 'ext' ~ i) }}
password={{ vars().get(ext_pass, '') }}

[{{ vars().get(ext_name, 'ext' ~ i) }}-aor]
type=aor
max_contacts=1
{% endif %}
{% endfor %}
```

Update `config/asterisk/extensions.conf.j2` — cascading forward:
```jinja2
[forward]
; Cascading forward: try internal extensions, then SIP trunk, then AI takes message
exten => s,1,NoOp(Forwarding call)
{% for i in range(1, 4) %}
{% set ext_name_key = 'sip_extension_' ~ i ~ '_name' %}
{% if vars().get(ext_name_key) %}
 same => n,Dial(PJSIP/{{ vars().get(ext_name_key) }},15)  ; Try extension {{ i }} for 15s
{% endif %}
{% endfor %}
 same => n,Dial(PJSIP/{{ sip_forward_number }}@{% if sip_outbound_server %}outbound-endpoint{% else %}inbound-endpoint{% endif %},15)  ; Try SIP trunk for 15s
 same => n,Goto(ai-message,s,1)  ; No answer -> AI takes message

[ai-message]
; Fall back to AI message-taking when no one answers
exten => s,1,NoOp(No answer — AI taking message)
 same => n,AudioSocket(127.0.0.1:9092)
 same => n,Hangup()
```

**Step 4: Run test to verify it passes**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_sip.py -v`
Expected: ALL PASSED

**Step 5: Commit**

```bash
git add config/ app/routes/sip.py app/templates/sip.html tests/test_sip.py
git commit -m "feat: internal SIP extensions with cascading forward (extension -> trunk -> AI message)"
```

---

### Task 6: Asterisk Config Apply Button

**Files:**
- Modify: `voice-secretary/app/routes/sip.py` (add apply endpoint)
- Modify: `voice-secretary/app/templates/sip.html` (add apply button)
- Test: `voice-secretary/tests/test_sip_apply.py`

**Step 1: Write the failing test**

```python
# tests/test_sip_apply.py
import tempfile
import os
import pytest
from app import create_app
from app.helpers import set_config


@pytest.fixture
def client():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app({"TESTING": True, "DATABASE": db_path})
    app.config["_DB_PATH"] = db_path
    app.config["ASTERISK_CONFIG_DIR"] = tempfile.mkdtemp()
    yield app.test_client()
    os.unlink(db_path)


def test_apply_config_generates_files(client):
    db_path = client.application.config["_DB_PATH"]
    config_dir = client.application.config["ASTERISK_CONFIG_DIR"]
    set_config("sip.inbound_server", "sip.example.com", "sip", db_path)
    set_config("sip.inbound_username", "user", "sip", db_path)
    set_config("sip.inbound_password", "pass", "sip", db_path)
    set_config("sip.inbound_port", "5060", "sip", db_path)
    set_config("sip.forward_number", "+41791234567", "sip", db_path)

    response = client.post("/sip/apply", follow_redirects=True)
    assert response.status_code == 200

    # Check files were written
    assert os.path.exists(os.path.join(config_dir, "pjsip.conf"))
    assert os.path.exists(os.path.join(config_dir, "extensions.conf"))

    # Check content
    with open(os.path.join(config_dir, "pjsip.conf")) as f:
        content = f.read()
    assert "sip.example.com" in content
```

**Step 2: Run test to verify it fails**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_sip_apply.py -v`
Expected: FAIL

**Step 3: Implement apply endpoint**

Add to `app/routes/sip.py`:

```python
@bp.route("/sip/apply", methods=["POST"])
def apply_config():
    """Generate Asterisk config files from current settings and write to disk."""
    db = _db_path()
    config_dir = current_app.config.get("ASTERISK_CONFIG_DIR", "/etc/asterisk")

    # Load all SIP config
    config = {}
    for key in SIP_FIELDS:
        config[key] = get_config(key, default=SIP_DEFAULTS.get(key, ""), db_path=db)

    from config.asterisk_gen import render_pjsip_conf, render_extensions_conf

    try:
        pjsip = render_pjsip_conf(config)
        extensions = render_extensions_conf(config)

        os.makedirs(config_dir, exist_ok=True)
        with open(os.path.join(config_dir, "pjsip.conf"), "w") as f:
            f.write(pjsip)
        with open(os.path.join(config_dir, "extensions.conf"), "w") as f:
            f.write(extensions)

        # Try to reload Asterisk (will fail on dev machines, that's OK)
        try:
            import subprocess
            subprocess.run(["asterisk", "-rx", "core reload"], capture_output=True, timeout=5)
            flash("Config applied and Asterisk reloaded.", "success")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            flash("Config files written. Asterisk not found (will apply on Pi).", "success")
    except Exception as e:
        flash(f"Error applying config: {e}", "error")

    return redirect(url_for("sip.index"))
```

Add `import os` to the imports in sip.py.

Add apply button to `app/templates/sip.html` after the save button:
```html
<form method="post" action="{{ url_for('sip.apply_config') }}" style="display:inline; margin-left: 1rem;">
    <button type="submit" class="outline">Apply to Asterisk</button>
</form>
```

**Step 4: Run test to verify it passes**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_sip_apply.py -v`
Expected: 1 PASSED

**Step 5: Commit**

```bash
git add app/routes/sip.py app/templates/sip.html tests/test_sip_apply.py
git commit -m "feat: apply button generates Asterisk config files and reloads"
```

---

### Task 7: WebSocket Live Call Status

**Files:**
- Create: `voice-secretary/app/websocket.py`
- Modify: `voice-secretary/app/__init__.py` (integrate SocketIO)
- Modify: `voice-secretary/app/templates/base.html` (add socket.io.js)
- Modify: `voice-secretary/app/templates/dashboard.html` (live call indicator)
- Test: `voice-secretary/tests/test_websocket.py`

**Step 1: Write the failing test**

```python
# tests/test_websocket.py
import tempfile
import os
import pytest
from app.websocket import CallStatusBroadcaster


def test_broadcaster_tracks_active_calls():
    broadcaster = CallStatusBroadcaster()
    broadcaster.call_started("uuid-1", "+41791111111")
    assert broadcaster.active_calls == 1
    assert broadcaster.get_status()["active_calls"] == 1


def test_broadcaster_removes_ended_calls():
    broadcaster = CallStatusBroadcaster()
    broadcaster.call_started("uuid-1", "+41791111111")
    broadcaster.call_ended("uuid-1")
    assert broadcaster.active_calls == 0


def test_broadcaster_formats_status():
    broadcaster = CallStatusBroadcaster()
    broadcaster.call_started("uuid-1", "+41791234567")
    status = broadcaster.get_status()
    assert status["active_calls"] == 1
    assert "+41791234567" in str(status["calls"])
```

**Step 2: Run test to verify it fails**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_websocket.py -v`
Expected: FAIL

**Step 3: Implement WebSocket broadcaster**

```python
# app/websocket.py
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class CallStatusBroadcaster:
    """Tracks active calls and provides status for the dashboard."""

    def __init__(self):
        self._calls = {}  # uuid -> call info

    @property
    def active_calls(self):
        return len(self._calls)

    def call_started(self, call_uuid, caller_number):
        self._calls[str(call_uuid)] = {
            "uuid": str(call_uuid),
            "caller_number": caller_number,
            "started_at": datetime.now().isoformat(),
            "state": "ringing",
        }
        logger.info(f"Call started: {call_uuid} from {caller_number}")

    def call_state_changed(self, call_uuid, state):
        key = str(call_uuid)
        if key in self._calls:
            self._calls[key]["state"] = state

    def call_ended(self, call_uuid):
        key = str(call_uuid)
        if key in self._calls:
            del self._calls[key]
            logger.info(f"Call ended: {call_uuid}")

    def get_status(self):
        return {
            "active_calls": self.active_calls,
            "calls": list(self._calls.values()),
        }


# Singleton for the app
call_status = CallStatusBroadcaster()
```

Add SocketIO client script to `app/templates/base.html` (download socket.io.min.js like htmx):
```bash
curl -sL https://cdn.socket.io/4.7.5/socket.io.min.js -o app/static/js/socket.io.min.js
```

Add to base.html head:
```html
<script src="{{ url_for('static', filename='js/socket.io.min.js') }}" defer></script>
```

Add live call indicator to `app/templates/dashboard.html` before the Recent Calls section:
```html
<div id="live-call-indicator" style="display:none; padding: 1rem; background: var(--accent); border-radius: 8px; color: #fff; margin-bottom: 1rem;">
    <strong>LIVE:</strong> <span id="live-call-info">No active calls</span>
</div>
```

**Step 4: Run test to verify it passes**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_websocket.py -v`
Expected: 3 PASSED

**Step 5: Commit**

```bash
git add app/websocket.py app/templates/base.html app/templates/dashboard.html app/static/js/socket.io.min.js tests/test_websocket.py
git commit -m "feat: WebSocket call status broadcaster with live call indicator"
```

---

### Task 8: Full Test Suite + Final Polish

**Step 1: Run full test suite**

Run: `cd voice-secretary && .venv/bin/pytest tests/ -v`
Expected: ALL PASSED (~120+ tests)

**Step 2: Update pi-gen stage to include engine**

Update `pi-gen/stage-voicesec/01-install-app.sh` to also copy `engine/` and `integrations/` directories.

**Step 3: Verify the app runs**

Run: `cd voice-secretary && make run` — verify dashboard loads, all screens work.

**Step 4: Commit**

```bash
git add -A
git commit -m "chore: Phase 4 complete - orchestrator, AudioSocket, call sessions, extensions, WebSocket"
```

---

## Phase 4 Summary

After completing all 8 tasks, you have:

- **TTS Cache** — pre-renders greeting and vacation messages to WAV for instant playback
- **LLM Tool Calling** — Ollama chat with tool definitions, handles tool_call responses
- **CallSession** — manages full conversation flow: greeting → conversation → tool calls → forward/message/end
- **AudioSocket Server** — TCP server on port 9092, receives audio from Asterisk, parses the protocol
- **Internal SIP Extensions** — up to 3 LAN SIP phones registered in Asterisk, cascading forward (extension → trunk → AI message)
- **Config Apply Button** — generates pjsip.conf + extensions.conf from DB, writes to disk, reloads Asterisk
- **WebSocket Live Status** — CallStatusBroadcaster tracks active calls, dashboard shows live indicator
- **~120+ passing tests**

**The call flow is now:**
```
Phone call → Asterisk (inbound SIP) → AudioSocket → Engine
  → Check vacation? → Play WAV, offer message
  → No vacation → Greeting → STT → LLM (with tools + knowledge rules)
    → LLM calls check_availability → forward/take_message
    → Forward: try extension(15s) → try trunk(15s) → AI takes message
    → Take message: record caller name + reason → email summary
  → TTS → audio back to caller via AudioSocket
```

**Next:** Phase 5 (Production hardening) — systemd watchdog, thermal monitoring, dashboard login, first-run wizard, one-command installer.
