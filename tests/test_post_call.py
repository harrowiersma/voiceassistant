import tempfile, os, json
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
