# tests/test_call_session.py
import tempfile, os, json
from unittest.mock import MagicMock
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
    set_config("persona.company_name", "TestCo", "persona", path)
    set_config("persona.greeting", "Hello, you've reached {company}.", "persona", path)
    set_config("persona.personality", "Professional and friendly.", "persona", path)
    set_config("persona.unavailable_message", "They are not available.", "persona", path)
    set_config("availability.manual_override", "auto", "availability", path)
    set_config("sip.forward_number", "+41791234567", "sip", path)
    set_config("ai.llm_model", "llama3.2:1b", "ai", path)
    yield path
    os.unlink(path)


def test_call_session_creates(db_path):
    from engine.call_session import CallSession
    session = CallSession(caller_number="+41791111111", db_path=db_path)
    assert session.caller_number == "+41791111111"
    assert session.state == "greeting"
    assert session.transcript == []


def test_call_session_greeting(db_path):
    from engine.call_session import CallSession
    session = CallSession(caller_number="+41791111111", db_path=db_path)
    greeting = session.get_greeting_text()
    assert "TestCo" in greeting


def test_call_session_process_turn(db_path):
    from engine.call_session import CallSession
    session = CallSession(caller_number="+41791111111", db_path=db_path)
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
    tool_response = {
        "role": "assistant", "content": "",
        "tool_calls": [{"function": {"name": "check_availability", "arguments": {}}}],
    }
    mock_llm = MagicMock()
    mock_llm.chat.side_effect = [tool_response, "They're available! Let me transfer you."]
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
    action = session.handle_action({"action": "forward", "number": "+41791234567"})
    assert action["type"] == "forward"
    assert action["number"] == "+41791234567"


def test_call_session_end_call(db_path):
    from engine.call_session import CallSession
    session = CallSession(caller_number="+41791111111", db_path=db_path)
    session.transcript = [{"role": "caller", "text": "Hello"}, {"role": "assistant", "text": "Hi"}]
    result = session.end_call(reason="caller_goodbye")
    assert "action_taken" in result
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
    response = session.process_turn("")
    assert session.silence_count == 1
    assert "still there" in response.lower()


def test_call_session_with_persona(db_path):
    from engine.call_session import CallSession
    conn = get_db_connection(db_path)
    conn.execute(
        "INSERT INTO personas (name, company_name, greeting, personality, unavailable_message, calendar_type) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("Sales", "Sales Dept", "Hello, sales here!", "Helpful.", "Sales closed.", "none"),
    )
    conn.commit()
    conn.close()
    session = CallSession(caller_number="+41791111111", db_path=db_path, persona_id=2)
    greeting = session.get_greeting_text()
    assert "sales" in greeting.lower()
