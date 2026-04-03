# Voice Secretary Phase 3: Availability + Actions

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Complete the secretary flow: check Teams presence via MS Graph, forward calls or take messages, send email summaries, create calendar entries for callbacks, and display a searchable call log. All configured via dashboard screens.

**Architecture:** MS Graph OAuth integration for Teams presence + calendar. LLM tool calling via Ollama for structured actions (forward, take message, suggest callback times). Post-call action engine sends email summaries and creates calendar entries. Call log with HTMX partial loading and WebSocket real-time updates.

**Tech Stack:** Python 3.11+, Flask, HTMX, Pico CSS, SQLite, MSAL (MS Graph auth), SMTP (email), Ollama (tool calling)

**Design reference:** `/Users/harrowiersma/Documents/CLAUDE/assistant/develop.md` (full spec)

**Phase 2 codebase:** `/Users/harrowiersma/Documents/CLAUDE/assistant/voice-secretary/` (64 tests passing)

---

### Task 1: MS Graph Client (integrations/msgraph.py)

**Files:**
- Create: `voice-secretary/integrations/__init__.py`
- Create: `voice-secretary/integrations/msgraph.py`
- Test: `voice-secretary/tests/test_msgraph.py`

**Step 1: Write the failing test**

```python
# tests/test_msgraph.py
import tempfile
import os
import json
from unittest.mock import patch, MagicMock
import pytest
from db.init_db import init_db
from db.connection import get_db_connection
from app.helpers import set_config


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    # Seed OAuth token
    conn = get_db_connection(path)
    conn.execute(
        "INSERT INTO oauth_tokens (provider, access_token, refresh_token, expires_at, scopes) "
        "VALUES (?, ?, ?, datetime('now', '+1 hour'), ?)",
        ("microsoft", "test_access_token", "test_refresh_token", "Presence.Read Calendars.Read"),
    )
    conn.commit()
    conn.close()
    # Seed Graph config
    set_config("graph.client_id", "test-client-id", "graph", path)
    set_config("graph.client_secret", "test-client-secret", "graph", path)
    set_config("graph.tenant_id", "test-tenant-id", "graph", path)
    yield path
    os.unlink(path)


def _mock_urlopen(response_data, status=200):
    """Create a mock urllib response."""
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.read.return_value = json.dumps(response_data).encode()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def test_check_presence_available(db_path):
    from integrations.msgraph import MSGraphClient
    client = MSGraphClient(db_path)
    with patch("urllib.request.urlopen") as mock:
        mock.return_value = _mock_urlopen({"availability": "Available", "activity": "Available"})
        result = client.check_presence()
    assert result == "available"


def test_check_presence_busy(db_path):
    from integrations.msgraph import MSGraphClient
    client = MSGraphClient(db_path)
    with patch("urllib.request.urlopen") as mock:
        mock.return_value = _mock_urlopen({"availability": "Busy", "activity": "InAMeeting"})
        result = client.check_presence()
    assert result == "busy"


def test_check_presence_dnd(db_path):
    from integrations.msgraph import MSGraphClient
    client = MSGraphClient(db_path)
    with patch("urllib.request.urlopen") as mock:
        mock.return_value = _mock_urlopen({"availability": "DoNotDisturb", "activity": "Presenting"})
        result = client.check_presence()
    assert result == "dnd"


def test_check_presence_away(db_path):
    from integrations.msgraph import MSGraphClient
    client = MSGraphClient(db_path)
    with patch("urllib.request.urlopen") as mock:
        mock.return_value = _mock_urlopen({"availability": "Away", "activity": "Away"})
        result = client.check_presence()
    assert result == "away"


def test_check_presence_timeout_returns_unknown(db_path):
    from integrations.msgraph import MSGraphClient
    client = MSGraphClient(db_path)
    with patch("urllib.request.urlopen") as mock:
        mock.side_effect = TimeoutError("timed out")
        result = client.check_presence()
    assert result == "unknown"


def test_get_free_slots(db_path):
    from integrations.msgraph import MSGraphClient
    client = MSGraphClient(db_path)
    cal_response = {
        "value": [
            {"start": {"dateTime": "2026-04-02T09:00:00"}, "end": {"dateTime": "2026-04-02T10:00:00"}, "subject": "Meeting"},
            {"start": {"dateTime": "2026-04-02T14:00:00"}, "end": {"dateTime": "2026-04-02T15:00:00"}, "subject": "Call"},
        ]
    }
    with patch("urllib.request.urlopen") as mock:
        mock.return_value = _mock_urlopen(cal_response)
        slots = client.get_free_slots(date="2026-04-02", business_start=9, business_end=17)
    # Should find gaps between meetings
    assert isinstance(slots, list)
    assert len(slots) > 0


def test_no_token_returns_not_configured(db_path):
    from integrations.msgraph import MSGraphClient
    # Remove token
    conn = get_db_connection(db_path)
    conn.execute("DELETE FROM oauth_tokens WHERE provider = 'microsoft'")
    conn.commit()
    conn.close()
    client = MSGraphClient(db_path)
    result = client.check_presence()
    assert result == "not_configured"
```

**Step 2: Run test to verify it fails**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_msgraph.py -v`
Expected: FAIL (module doesn't exist)

**Step 3: Implement MS Graph client**

```python
# integrations/__init__.py
# (empty)
```

```python
# integrations/msgraph.py
import json
import logging
import urllib.request
from datetime import datetime, timedelta
from db.connection import get_db_connection
from app.helpers import get_config

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

PRESENCE_MAP = {
    "Available": "available",
    "AvailableIdle": "available",
    "Busy": "busy",
    "BusyIdle": "busy",
    "DoNotDisturb": "dnd",
    "BeRightBack": "away",
    "Away": "away",
    "Offline": "offline",
    "PresenceUnknown": "unknown",
}


class MSGraphClient:
    def __init__(self, db_path=None):
        self.db_path = db_path

    def _get_token(self):
        """Get access token from DB. Returns None if not configured or expired."""
        conn = get_db_connection(self.db_path)
        row = conn.execute(
            "SELECT access_token, refresh_token, expires_at FROM oauth_tokens WHERE provider = 'microsoft'"
        ).fetchone()
        conn.close()
        if not row:
            return None
        return row["access_token"]

    def _graph_get(self, endpoint):
        """Make authenticated GET request to MS Graph API."""
        token = self._get_token()
        if not token:
            return None
        req = urllib.request.Request(
            f"{GRAPH_BASE}{endpoint}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())

    def check_presence(self):
        """Check Teams presence status. Returns: available, busy, dnd, away, offline, unknown, not_configured."""
        token = self._get_token()
        if not token:
            return "not_configured"
        try:
            data = self._graph_get("/me/presence")
            if data and "availability" in data:
                return PRESENCE_MAP.get(data["availability"], "unknown")
            return "unknown"
        except Exception as e:
            logger.error(f"Presence check failed: {e}")
            return "unknown"

    def get_free_slots(self, date=None, business_start=9, business_end=17):
        """Get free time slots for a given date. Returns list of (start, end) tuples."""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        try:
            start = f"{date}T{business_start:02d}:00:00"
            end = f"{date}T{business_end:02d}:00:00"
            data = self._graph_get(
                f"/me/calendarView?startDateTime={start}&endDateTime={end}&$select=start,end,subject"
            )
            if not data or "value" not in data:
                return []

            # Parse busy times
            busy = []
            for event in data["value"]:
                ev_start = datetime.fromisoformat(event["start"]["dateTime"])
                ev_end = datetime.fromisoformat(event["end"]["dateTime"])
                busy.append((ev_start, ev_end))
            busy.sort(key=lambda x: x[0])

            # Find gaps
            slots = []
            current = datetime.fromisoformat(f"{date}T{business_start:02d}:00:00")
            day_end = datetime.fromisoformat(f"{date}T{business_end:02d}:00:00")

            for ev_start, ev_end in busy:
                if current < ev_start:
                    slots.append({
                        "start": current.strftime("%H:%M"),
                        "end": ev_start.strftime("%H:%M"),
                        "duration_min": int((ev_start - current).total_seconds() / 60),
                    })
                current = max(current, ev_end)

            if current < day_end:
                slots.append({
                    "start": current.strftime("%H:%M"),
                    "end": day_end.strftime("%H:%M"),
                    "duration_min": int((day_end - current).total_seconds() / 60),
                })

            return [s for s in slots if s["duration_min"] >= 15]  # Min 15min slots
        except Exception as e:
            logger.error(f"Free slots query failed: {e}")
            return []
```

**Step 4: Run test to verify it passes**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_msgraph.py -v`
Expected: 7 PASSED

**Step 5: Commit**

```bash
git add integrations/ tests/test_msgraph.py
git commit -m "feat: MS Graph client with presence check and calendar free slots"
```

---

### Task 2: LLM Tool Definitions (engine/tools.py)

**Files:**
- Create: `voice-secretary/engine/tools.py`
- Test: `voice-secretary/tests/test_tools.py`

**Step 1: Write the failing test**

```python
# tests/test_tools.py
import json
import pytest
from engine.tools import TOOL_DEFINITIONS, execute_tool


def test_tool_definitions_are_valid_json_schema():
    for tool in TOOL_DEFINITIONS:
        assert "type" in tool
        assert tool["type"] == "function"
        assert "function" in tool
        assert "name" in tool["function"]
        assert "description" in tool["function"]
        assert "parameters" in tool["function"]


def test_all_expected_tools_defined():
    names = {t["function"]["name"] for t in TOOL_DEFINITIONS}
    assert "check_availability" in names
    assert "forward_call" in names
    assert "take_message" in names
    assert "suggest_callback_times" in names
    assert "end_call" in names


def test_execute_check_availability_returns_dict():
    # Mock context that doesn't need real Graph API
    result = execute_tool("check_availability", {}, db_path=None, mock_presence="available")
    assert isinstance(result, dict)
    assert "status" in result


def test_execute_take_message_returns_confirmation():
    result = execute_tool("take_message", {
        "caller_name": "John Smith",
        "reason": "Wants to discuss the project",
        "callback_requested": True,
    }, db_path=None)
    assert isinstance(result, dict)
    assert result["success"] is True


def test_execute_end_call():
    result = execute_tool("end_call", {"reason": "caller_goodbye"}, db_path=None)
    assert isinstance(result, dict)
    assert result["action"] == "hangup"


def test_execute_unknown_tool_returns_error():
    result = execute_tool("nonexistent_tool", {}, db_path=None)
    assert "error" in result
```

**Step 2: Run test to verify it fails**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_tools.py -v`
Expected: FAIL

**Step 3: Implement tools**

```python
# engine/tools.py
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "check_availability",
            "description": "Check if the person is available to take a call right now. Returns their current status.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forward_call",
            "description": "Transfer this call to the person's phone number.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "take_message",
            "description": "Record a message from the caller with their name and reason for calling.",
            "parameters": {
                "type": "object",
                "properties": {
                    "caller_name": {"type": "string", "description": "Name of the caller"},
                    "reason": {"type": "string", "description": "Why they are calling"},
                    "callback_requested": {"type": "boolean", "description": "Whether caller wants a callback"},
                },
                "required": ["caller_name", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_callback_times",
            "description": "Look up available callback times from the calendar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date to check (YYYY-MM-DD). Defaults to today."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "end_call",
            "description": "Politely end the call.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "Why the call is ending (caller_goodbye, no_response, max_duration)"},
                },
                "required": ["reason"],
            },
        },
    },
]


def execute_tool(tool_name, arguments, db_path=None, mock_presence=None):
    """Execute a tool call and return the result dict."""
    handlers = {
        "check_availability": _handle_check_availability,
        "forward_call": _handle_forward_call,
        "take_message": _handle_take_message,
        "suggest_callback_times": _handle_suggest_callback_times,
        "end_call": _handle_end_call,
    }
    handler = handlers.get(tool_name)
    if not handler:
        return {"error": f"Unknown tool: {tool_name}"}
    return handler(arguments, db_path=db_path, mock_presence=mock_presence)


def _handle_check_availability(args, db_path=None, mock_presence=None):
    if mock_presence:
        return {"status": mock_presence, "action": "forward" if mock_presence == "available" else "take_message"}
    try:
        from integrations.msgraph import MSGraphClient
        client = MSGraphClient(db_path)
        presence = client.check_presence()
        action = "forward" if presence == "available" else "take_message"
        return {"status": presence, "action": action}
    except Exception as e:
        logger.error(f"Availability check failed: {e}")
        return {"status": "unknown", "action": "take_message"}


def _handle_forward_call(args, db_path=None, **kwargs):
    from app.helpers import get_config
    forward_number = get_config("sip.forward_number", default="", db_path=db_path) if db_path else ""
    return {"action": "forward", "number": forward_number}


def _handle_take_message(args, db_path=None, **kwargs):
    return {
        "success": True,
        "caller_name": args.get("caller_name", "Unknown"),
        "reason": args.get("reason", ""),
        "callback_requested": args.get("callback_requested", False),
        "timestamp": datetime.now().isoformat(),
    }


def _handle_suggest_callback_times(args, db_path=None, **kwargs):
    try:
        from integrations.msgraph import MSGraphClient
        client = MSGraphClient(db_path)
        date = args.get("date")
        slots = client.get_free_slots(date=date)
        if slots:
            return {"available_times": slots}
        return {"available_times": [], "message": "No available slots found. Would you like to try another day?"}
    except Exception as e:
        logger.error(f"Callback times lookup failed: {e}")
        return {"available_times": [], "message": "Calendar unavailable. We'll call you back as soon as possible."}


def _handle_end_call(args, db_path=None, **kwargs):
    return {"action": "hangup", "reason": args.get("reason", "caller_goodbye")}
```

**Step 4: Run test to verify it passes**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_tools.py -v`
Expected: 6 PASSED

**Step 5: Commit**

```bash
git add engine/tools.py tests/test_tools.py
git commit -m "feat: LLM tool definitions for availability, forwarding, messaging, and callbacks"
```

---

### Task 3: Email Sender (integrations/email_sender.py)

**Files:**
- Create: `voice-secretary/integrations/email_sender.py`
- Test: `voice-secretary/tests/test_email.py`

**Step 1: Write the failing test**

```python
# tests/test_email.py
import tempfile
import os
from unittest.mock import patch, MagicMock
import pytest
from db.init_db import init_db
from app.helpers import set_config


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    set_config("actions.smtp_server", "smtp.example.com", "actions", path)
    set_config("actions.smtp_port", "587", "actions", path)
    set_config("actions.smtp_username", "user@example.com", "actions", path)
    set_config("actions.smtp_password", "password123", "actions", path)
    set_config("actions.email_to", "owner@example.com", "actions", path)
    set_config("actions.email_from", "secretary@example.com", "actions", path)
    yield path
    os.unlink(path)


def test_send_call_summary_constructs_email(db_path):
    from integrations.email_sender import EmailSender
    sender = EmailSender(db_path)
    with patch("smtplib.SMTP") as mock_smtp:
        mock_instance = MagicMock()
        mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_instance)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

        result = sender.send_call_summary(
            caller_name="John Smith",
            caller_number="+41791234567",
            reason="Wants to discuss the project",
            transcript="Hello, I'm calling about...",
            action_taken="message_taken",
        )
    assert result is True


def test_send_fails_without_config():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    from integrations.email_sender import EmailSender
    sender = EmailSender(path)
    result = sender.send_call_summary(
        caller_name="John", caller_number="+41791234567",
        reason="Test", transcript="Test", action_taken="test",
    )
    assert result is False
    os.unlink(path)


def test_email_template_contains_call_info(db_path):
    from integrations.email_sender import EmailSender
    sender = EmailSender(db_path)
    body = sender._render_summary(
        caller_name="John Smith",
        caller_number="+41791234567",
        reason="Project discussion",
        transcript="Hello, I'm calling about the project.",
        action_taken="message_taken",
    )
    assert "John Smith" in body
    assert "+41791234567" in body
    assert "Project discussion" in body
```

**Step 2: Run test to verify it fails**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_email.py -v`
Expected: FAIL

**Step 3: Implement email sender**

```python
# integrations/email_sender.py
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from app.helpers import get_config

logger = logging.getLogger(__name__)


class EmailSender:
    def __init__(self, db_path=None):
        self.db_path = db_path

    def _get_smtp_config(self):
        server = get_config("actions.smtp_server", db_path=self.db_path)
        if not server:
            return None
        return {
            "server": server,
            "port": int(get_config("actions.smtp_port", default="587", db_path=self.db_path)),
            "username": get_config("actions.smtp_username", default="", db_path=self.db_path),
            "password": get_config("actions.smtp_password", default="", db_path=self.db_path),
            "email_to": get_config("actions.email_to", default="", db_path=self.db_path),
            "email_from": get_config("actions.email_from", default="", db_path=self.db_path),
        }

    def _render_summary(self, caller_name, caller_number, reason, transcript, action_taken):
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        return f"""Voice Secretary - Call Summary
{'=' * 40}

Date/Time:    {now}
Caller:       {caller_name}
Number:       {caller_number}
Reason:       {reason}
Action Taken: {action_taken}

Transcript:
{'-' * 40}
{transcript}
{'-' * 40}

This is an automated message from Voice Secretary.
"""

    def send_call_summary(self, caller_name, caller_number, reason, transcript, action_taken):
        config = self._get_smtp_config()
        if not config:
            logger.warning("SMTP not configured, cannot send email")
            return False
        try:
            body = self._render_summary(caller_name, caller_number, reason, transcript, action_taken)
            msg = MIMEMultipart()
            msg["From"] = config["email_from"]
            msg["To"] = config["email_to"]
            msg["Subject"] = f"Voice Secretary: Call from {caller_name}"
            msg.attach(MIMEText(body, "plain"))

            with smtplib.SMTP(config["server"], config["port"]) as server:
                server.starttls()
                server.login(config["username"], config["password"])
                server.send_message(msg)
            logger.info(f"Call summary email sent for {caller_name}")
            return True
        except Exception as e:
            logger.error(f"Email send failed: {e}")
            return False
```

**Step 4: Run test to verify it passes**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_email.py -v`
Expected: 3 PASSED

**Step 5: Commit**

```bash
git add integrations/email_sender.py tests/test_email.py
git commit -m "feat: email sender for post-call summary notifications"
```

---

### Task 4: Availability Rules Screen

**Files:**
- Modify: `voice-secretary/app/routes/availability.py`
- Modify: `voice-secretary/app/templates/availability.html`
- Test: `voice-secretary/tests/test_availability.py`

**Step 1: Write the failing test**

```python
# tests/test_availability.py
import tempfile
import os
import pytest
from app import create_app
from app.helpers import get_config


@pytest.fixture
def client():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app({"TESTING": True, "DATABASE": db_path})
    app.config["_DB_PATH"] = db_path
    yield app.test_client()
    os.unlink(db_path)


def test_availability_page_has_form(client):
    response = client.get("/availability")
    html = response.data.decode()
    assert 'name="availability.manual_override"' in html
    assert 'name="availability.business_hours_start"' in html
    assert 'name="availability.business_hours_end"' in html


def test_availability_has_presence_mapping(client):
    response = client.get("/availability")
    html = response.data.decode()
    assert "Available" in html
    assert "Busy" in html
    assert "Do Not Disturb" in html


def test_availability_has_graph_section(client):
    response = client.get("/availability")
    html = response.data.decode()
    assert "MS Graph" in html or "Microsoft" in html
    assert 'name="graph.client_id"' in html


def test_availability_save(client):
    response = client.post("/availability/save", data={
        "availability.manual_override": "auto",
        "availability.business_hours_start": "09:00",
        "availability.business_hours_end": "17:00",
        "availability.action_available": "forward",
        "availability.action_busy": "take_message",
        "availability.action_dnd": "take_message",
        "availability.action_away": "take_message",
        "graph.client_id": "",
        "graph.client_secret": "",
        "graph.tenant_id": "",
    }, follow_redirects=True)
    assert response.status_code == 200


def test_availability_persists(client):
    db_path = client.application.config["_DB_PATH"]
    client.post("/availability/save", data={
        "availability.manual_override": "unavailable",
        "availability.business_hours_start": "08:00",
        "availability.business_hours_end": "18:00",
        "availability.action_available": "forward",
        "availability.action_busy": "take_message",
        "availability.action_dnd": "take_message",
        "availability.action_away": "take_message",
        "graph.client_id": "abc123",
        "graph.client_secret": "secret",
        "graph.tenant_id": "tenant",
    })
    assert get_config("availability.manual_override", db_path=db_path) == "unavailable"
    assert get_config("availability.business_hours_start", db_path=db_path) == "08:00"
    assert get_config("graph.client_id", db_path=db_path) == "abc123"
```

**Step 2: Run test to verify it fails**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_availability.py -v`
Expected: FAIL

**Step 3: Implement availability route and template**

Route: `app/routes/availability.py` — Same pattern as sip.py/persona.py with AVAILABILITY_FIELDS list (manual_override, business_hours_start/end, action_available/busy/dnd/away) plus graph.client_id/client_secret/tenant_id. Add AVAILABILITY_DEFAULTS to `config/defaults.py`.

Template: `app/templates/availability.html` — Extends base.html. Sections:
- Manual Override: select with options "auto", "available", "unavailable"
- Business Hours: time inputs for start and end
- Presence Mapping: table showing each Teams status (Available, Busy, DND, Away) with select for action (forward / take_message / voicemail)
- MS Graph Setup: text inputs for client_id, client_secret, tenant_id with help text
- Save button

**Step 4: Run test to verify it passes**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_availability.py -v`
Expected: 5 PASSED

**Step 5: Commit**

```bash
git add app/routes/availability.py app/templates/availability.html config/defaults.py tests/test_availability.py
git commit -m "feat: availability rules screen with presence mapping and MS Graph config"
```

---

### Task 5: Actions Screen (Email/Calendar Config)

**Files:**
- Modify: `voice-secretary/app/routes/actions.py`
- Modify: `voice-secretary/app/templates/actions.html`
- Test: `voice-secretary/tests/test_actions.py`

**Step 1: Write the failing test**

```python
# tests/test_actions.py
import tempfile
import os
import pytest
from app import create_app
from app.helpers import get_config


@pytest.fixture
def client():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app({"TESTING": True, "DATABASE": db_path})
    app.config["_DB_PATH"] = db_path
    yield app.test_client()
    os.unlink(db_path)


def test_actions_page_has_smtp_form(client):
    response = client.get("/actions")
    html = response.data.decode()
    assert 'name="actions.smtp_server"' in html
    assert 'name="actions.smtp_port"' in html
    assert 'name="actions.smtp_username"' in html
    assert 'name="actions.email_to"' in html


def test_actions_page_has_notification_prefs(client):
    response = client.get("/actions")
    html = response.data.decode()
    assert 'name="actions.notify_on"' in html


def test_actions_save(client):
    response = client.post("/actions/save", data={
        "actions.smtp_server": "smtp.gmail.com",
        "actions.smtp_port": "587",
        "actions.smtp_username": "user@gmail.com",
        "actions.smtp_password": "app-password",
        "actions.email_to": "owner@gmail.com",
        "actions.email_from": "secretary@gmail.com",
        "actions.notify_on": "message_only",
    }, follow_redirects=True)
    assert response.status_code == 200


def test_actions_persists(client):
    db_path = client.application.config["_DB_PATH"]
    client.post("/actions/save", data={
        "actions.smtp_server": "smtp.gmail.com",
        "actions.smtp_port": "587",
        "actions.smtp_username": "user@gmail.com",
        "actions.smtp_password": "app-password",
        "actions.email_to": "owner@gmail.com",
        "actions.email_from": "secretary@gmail.com",
        "actions.notify_on": "all_calls",
    })
    assert get_config("actions.smtp_server", db_path=db_path) == "smtp.gmail.com"
    assert get_config("actions.notify_on", db_path=db_path) == "all_calls"
```

**Step 2: Run test to verify it fails**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_actions.py -v`
Expected: FAIL

**Step 3: Implement actions route and template**

Route: `app/routes/actions.py` — Same form pattern. ACTIONS_FIELDS list: smtp_server, smtp_port, smtp_username, smtp_password, email_to, email_from, notify_on. Add ACTIONS_DEFAULTS to `config/defaults.py`.

Template: `app/templates/actions.html` — Extends base.html. Sections:
- SMTP Settings: server, port, username, password inputs
- Recipients: email_to, email_from inputs
- Notification Preferences: select with "all_calls", "message_only", "never"
- Save button

**Step 4: Run test to verify it passes**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_actions.py -v`
Expected: 4 PASSED

**Step 5: Commit**

```bash
git add app/routes/actions.py app/templates/actions.html config/defaults.py tests/test_actions.py
git commit -m "feat: actions screen with SMTP email config and notification preferences"
```

---

### Task 6: Call Log Screen

**Files:**
- Modify: `voice-secretary/app/routes/calls.py`
- Modify: `voice-secretary/app/templates/calls.html`
- Create: `voice-secretary/app/routes/api.py` (add /api/calls endpoints)
- Test: `voice-secretary/tests/test_calls.py`

**Step 1: Write the failing test**

```python
# tests/test_calls.py
import tempfile
import os
import json
from datetime import datetime
import pytest
from app import create_app
from db.connection import get_db_connection


@pytest.fixture
def client():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app({"TESTING": True, "DATABASE": db_path})
    app.config["_DB_PATH"] = db_path
    yield app.test_client()
    os.unlink(db_path)


def _seed_calls(db_path, count=5):
    conn = get_db_connection(db_path)
    for i in range(count):
        conn.execute(
            "INSERT INTO calls (started_at, caller_number, caller_name, duration_seconds, reason, action_taken, transcript) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                datetime(2026, 4, 2, 9 + i, 0).isoformat(),
                f"+4179{1000000 + i}",
                f"Caller {i + 1}",
                60 + i * 30,
                f"Reason {i + 1}",
                "message_taken" if i % 2 else "forwarded",
                json.dumps([{"role": "caller", "text": f"Hello, call {i + 1}"}]),
            ),
        )
    conn.commit()
    conn.close()


def test_calls_page_loads(client):
    response = client.get("/calls")
    assert response.status_code == 200
    assert b"Call Log" in response.data


def test_calls_page_shows_empty_state(client):
    response = client.get("/calls")
    assert b"No calls yet" in response.data


def test_calls_page_shows_calls(client):
    db_path = client.application.config["_DB_PATH"]
    _seed_calls(db_path, 3)
    response = client.get("/calls")
    html = response.data.decode()
    assert "Caller 1" in html
    assert "Caller 2" in html


def test_calls_api_returns_json(client):
    db_path = client.application.config["_DB_PATH"]
    _seed_calls(db_path, 2)
    response = client.get("/api/calls")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert "calls" in data
    assert len(data["calls"]) == 2


def test_calls_api_filter_by_action(client):
    db_path = client.application.config["_DB_PATH"]
    _seed_calls(db_path, 4)
    response = client.get("/api/calls?action=forwarded")
    data = json.loads(response.data)
    for call in data["calls"]:
        assert call["action_taken"] == "forwarded"
```

**Step 2: Run test to verify it fails**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_calls.py -v`
Expected: FAIL

**Step 3: Implement call log route, API, and template**

Route: `app/routes/calls.py` — GET /calls renders the call log page with recent calls from DB.

API (add to `app/routes/api.py`):
- GET /api/calls — returns JSON list of calls, supports ?action= filter
- GET /api/calls/<int:call_id> — returns single call with full transcript

Template: `app/templates/calls.html` — Extends base.html. Contains:
- Filter bar: select for action_taken, date range (optional)
- Table: date/time, caller, duration, reason, action taken
- Expandable rows (details tag) showing transcript
- Empty state when no calls

**Step 4: Run test to verify it passes**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_calls.py -v`
Expected: 5 PASSED

**Step 5: Commit**

```bash
git add app/routes/calls.py app/routes/api.py app/templates/calls.html tests/test_calls.py
git commit -m "feat: call log screen with filterable table and API"
```

---

### Task 7: Post-Call Action Engine

**Files:**
- Create: `voice-secretary/engine/post_call.py`
- Test: `voice-secretary/tests/test_post_call.py`

**Step 1: Write the failing test**

```python
# tests/test_post_call.py
import tempfile
import os
import json
from unittest.mock import patch, MagicMock
from datetime import datetime
import pytest
from db.init_db import init_db
from db.connection import get_db_connection
from app.helpers import set_config


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    set_config("actions.smtp_server", "smtp.example.com", "actions", path)
    set_config("actions.smtp_port", "587", "actions", path)
    set_config("actions.smtp_username", "user@example.com", "actions", path)
    set_config("actions.smtp_password", "pass", "actions", path)
    set_config("actions.email_to", "owner@example.com", "actions", path)
    set_config("actions.email_from", "secretary@example.com", "actions", path)
    set_config("actions.notify_on", "all_calls", "actions", path)
    yield path
    os.unlink(path)


def test_log_call_creates_db_record(db_path):
    from engine.post_call import log_call
    call_id = log_call(
        db_path=db_path,
        caller_number="+41791234567",
        caller_name="John Smith",
        reason="Project discussion",
        transcript=[{"role": "caller", "text": "Hello"}],
        action_taken="message_taken",
        duration_seconds=120,
    )
    assert call_id is not None
    conn = get_db_connection(db_path)
    row = conn.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone()
    conn.close()
    assert row["caller_name"] == "John Smith"
    assert row["action_taken"] == "message_taken"


def test_process_post_call_sends_email(db_path):
    from engine.post_call import process_post_call_actions
    with patch("integrations.email_sender.EmailSender.send_call_summary") as mock_send:
        mock_send.return_value = True
        result = process_post_call_actions(
            db_path=db_path,
            call_id=1,
            caller_name="John",
            caller_number="+41791234567",
            reason="Test",
            transcript="Hello",
            action_taken="message_taken",
        )
    mock_send.assert_called_once()
    assert result["email_sent"] is True


def test_process_post_call_skips_email_on_forward_when_message_only(db_path):
    set_config("actions.notify_on", "message_only", "actions", db_path)
    from engine.post_call import process_post_call_actions
    with patch("integrations.email_sender.EmailSender.send_call_summary") as mock_send:
        result = process_post_call_actions(
            db_path=db_path,
            call_id=1,
            caller_name="John",
            caller_number="+41791234567",
            reason="Test",
            transcript="Hello",
            action_taken="forwarded",
        )
    mock_send.assert_not_called()
    assert result["email_sent"] is False
```

**Step 2: Run test to verify it fails**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_post_call.py -v`
Expected: FAIL

**Step 3: Implement post-call action engine**

```python
# engine/post_call.py
import json
import logging
from datetime import datetime
from db.connection import get_db_connection
from app.helpers import get_config
from integrations.email_sender import EmailSender

logger = logging.getLogger(__name__)


def log_call(db_path, caller_number, caller_name, reason, transcript, action_taken, duration_seconds=0, **kwargs):
    """Log a completed call to the database. Returns the call ID."""
    conn = get_db_connection(db_path)
    cursor = conn.execute(
        "INSERT INTO calls (started_at, caller_number, caller_name, duration_seconds, reason, transcript, action_taken) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            datetime.now().isoformat(),
            caller_number,
            caller_name,
            duration_seconds,
            reason,
            json.dumps(transcript) if isinstance(transcript, list) else transcript,
            action_taken,
        ),
    )
    call_id = cursor.lastrowid
    conn.commit()
    conn.close()
    logger.info(f"Call logged: {call_id} from {caller_name} ({action_taken})")
    return call_id


def process_post_call_actions(db_path, call_id, caller_name, caller_number, reason, transcript, action_taken):
    """Run post-call actions (email, calendar) based on config."""
    result = {"email_sent": False, "calendar_created": False}

    notify_on = get_config("actions.notify_on", default="all_calls", db_path=db_path)

    # Check if we should send email
    should_email = False
    if notify_on == "all_calls":
        should_email = True
    elif notify_on == "message_only" and action_taken in ("message_taken", "voicemail"):
        should_email = True

    if should_email:
        sender = EmailSender(db_path)
        result["email_sent"] = sender.send_call_summary(
            caller_name=caller_name,
            caller_number=caller_number,
            reason=reason,
            transcript=transcript if isinstance(transcript, str) else json.dumps(transcript),
            action_taken=action_taken,
        )

    # Update call record
    conn = get_db_connection(db_path)
    conn.execute(
        "UPDATE calls SET email_sent = ?, calendar_created = ? WHERE id = ?",
        (result["email_sent"], result["calendar_created"], call_id),
    )
    conn.commit()
    conn.close()

    return result
```

**Step 4: Run test to verify it passes**

Run: `cd voice-secretary && .venv/bin/pytest tests/test_post_call.py -v`
Expected: 3 PASSED

**Step 5: Commit**

```bash
git add engine/post_call.py tests/test_post_call.py
git commit -m "feat: post-call action engine with email notifications and call logging"
```

---

### Task 8: Full Test Suite + Smoke Test

**Step 1: Run full test suite**

Run: `cd voice-secretary && .venv/bin/pytest tests/ -v`
Expected: ALL PASSED (~90+ tests)

**Step 2: Update requirements.txt**

Add `msal` for future MS Graph OAuth token flow (not needed for mocked tests but needed on Pi):

```
msal==1.31.*
```

Run: `cd voice-secretary && .venv/bin/pip install -r requirements.txt`

**Step 3: Verify the app runs**

Run: `cd voice-secretary && make run` — verify dashboard loads, all new screens work.

**Step 4: Commit**

```bash
git add -A
git commit -m "chore: Phase 3 complete - availability, actions, call log, MS Graph, email notifications"
```

---

## Phase 3 Summary

After completing all 8 tasks, you have:

- **MS Graph client** (presence check, calendar free slots, mock-tested)
- **LLM tool definitions** (check_availability, forward_call, take_message, suggest_callback_times, end_call)
- **Email sender** (SMTP-based call summary notifications)
- **Availability Rules screen** (manual override, business hours, presence-to-action mapping, MS Graph config)
- **Actions screen** (SMTP config, notification preferences)
- **Call Log screen** (filterable table with API, expandable transcripts)
- **Post-call action engine** (logs calls, sends email based on notification prefs)
- **~90+ passing tests**

**Next:** Phase 4 (Orchestrator + Polish) will wire everything together:
- AudioSocket bridge (Asterisk -> engine)
- Full call flow (STT -> LLM with tools -> TTS -> back to caller)
- WebSocket real-time updates
- First-run setup wizard
- systemd watchdog + thermal monitoring
