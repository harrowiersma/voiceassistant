"""Tests for MS Graph client — presence check and calendar free slots."""
import json
import os
import tempfile
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from db.init_db import init_db
from db.connection import get_db_connection
from app.helpers import set_config


def _mock_urlopen(response_data, status=200):
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.read.return_value = json.dumps(response_data).encode()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    conn = get_db_connection(path)
    conn.execute(
        "INSERT INTO oauth_tokens (provider, access_token, refresh_token, expires_at, scopes) "
        "VALUES (?, ?, ?, datetime('now', '+1 hour'), ?)",
        ("microsoft", "test_access_token", "test_refresh_token", "Presence.Read Calendars.Read"),
    )
    conn.commit()
    conn.close()
    set_config("graph.client_id", "test-client-id", "graph", path)
    set_config("graph.client_secret", "test-client-secret", "graph", path)
    set_config("graph.tenant_id", "test-tenant-id", "graph", path)
    yield path
    os.unlink(path)


# ── Presence tests ──────────────────────────────────────────────


@patch("urllib.request.urlopen")
def test_check_presence_available(mock_urlopen, db_path):
    from integrations.msgraph import MSGraphClient

    mock_urlopen.return_value = _mock_urlopen({"availability": "Available"})
    client = MSGraphClient(db_path)
    assert client.check_presence() == "available"


@patch("urllib.request.urlopen")
def test_check_presence_busy(mock_urlopen, db_path):
    from integrations.msgraph import MSGraphClient

    mock_urlopen.return_value = _mock_urlopen({"availability": "Busy"})
    client = MSGraphClient(db_path)
    assert client.check_presence() == "busy"


@patch("urllib.request.urlopen")
def test_check_presence_dnd(mock_urlopen, db_path):
    from integrations.msgraph import MSGraphClient

    mock_urlopen.return_value = _mock_urlopen({"availability": "DoNotDisturb"})
    client = MSGraphClient(db_path)
    assert client.check_presence() == "dnd"


@patch("urllib.request.urlopen")
def test_check_presence_away(mock_urlopen, db_path):
    from integrations.msgraph import MSGraphClient

    mock_urlopen.return_value = _mock_urlopen({"availability": "Away"})
    client = MSGraphClient(db_path)
    assert client.check_presence() == "away"


@patch("urllib.request.urlopen")
def test_check_presence_timeout_returns_unknown(mock_urlopen, db_path):
    from integrations.msgraph import MSGraphClient

    mock_urlopen.side_effect = TimeoutError("connection timed out")
    client = MSGraphClient(db_path)
    assert client.check_presence() == "unknown"


# ── Calendar free slots test ────────────────────────────────────


@patch("urllib.request.urlopen")
def test_get_free_slots(mock_urlopen, db_path):
    from integrations.msgraph import MSGraphClient

    # Two events: 10:00-11:00 and 14:00-15:00 on 2026-04-02
    calendar_response = {
        "value": [
            {
                "start": {"dateTime": "2026-04-02T10:00:00.0000000", "timeZone": "UTC"},
                "end": {"dateTime": "2026-04-02T11:00:00.0000000", "timeZone": "UTC"},
            },
            {
                "start": {"dateTime": "2026-04-02T14:00:00.0000000", "timeZone": "UTC"},
                "end": {"dateTime": "2026-04-02T15:00:00.0000000", "timeZone": "UTC"},
            },
        ]
    }
    mock_urlopen.return_value = _mock_urlopen(calendar_response)

    client = MSGraphClient(db_path)
    slots = client.get_free_slots("2026-04-02")

    # Expected free slots (business hours 09:00-17:00):
    #   09:00-10:00 (60 min)
    #   11:00-14:00 (180 min)
    #   15:00-17:00 (120 min)
    assert len(slots) == 3
    assert slots[0]["start"] == "09:00"
    assert slots[0]["end"] == "10:00"
    assert slots[0]["duration_min"] == 60
    assert slots[1]["start"] == "11:00"
    assert slots[1]["end"] == "14:00"
    assert slots[1]["duration_min"] == 180
    assert slots[2]["start"] == "15:00"
    assert slots[2]["end"] == "17:00"
    assert slots[2]["duration_min"] == 120


# ── No token test ───────────────────────────────────────────────


def test_no_token_returns_not_configured(db_path):
    from integrations.msgraph import MSGraphClient

    # Remove the token
    conn = get_db_connection(db_path)
    conn.execute("DELETE FROM oauth_tokens WHERE provider = 'microsoft'")
    conn.commit()
    conn.close()

    client = MSGraphClient(db_path)
    assert client.check_presence() == "not_configured"
