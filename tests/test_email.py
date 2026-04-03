# tests/test_email.py
import tempfile, os
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
            caller_name="John Smith", caller_number="+41791234567",
            reason="Project discussion", transcript="Hello, I'm calling about...",
            action_taken="message_taken",
        )
    assert result is True


def test_send_fails_without_config():
    import tempfile
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
        caller_name="John Smith", caller_number="+41791234567",
        reason="Project discussion", transcript="Hello, I'm calling about the project.",
        action_taken="message_taken",
    )
    assert "John Smith" in body
    assert "+41791234567" in body
    assert "Project discussion" in body
