"""Tests for Google Calendar client — free slots and busy check."""
import json
from unittest.mock import patch, MagicMock
import pytest


def _mock_response(data, status=200):
    mock = MagicMock()
    mock.status = status
    mock.read.return_value = json.dumps(data).encode()
    mock.__enter__ = MagicMock(return_value=mock)
    mock.__exit__ = MagicMock(return_value=False)
    return mock


def test_google_get_free_slots():
    from integrations.google_calendar import GoogleCalendarClient
    client = GoogleCalendarClient(access_token="test_token")
    events = {"items": [
        {"start": {"dateTime": "2026-04-02T10:00:00+02:00"}, "end": {"dateTime": "2026-04-02T11:00:00+02:00"}},
        {"start": {"dateTime": "2026-04-02T14:00:00+02:00"}, "end": {"dateTime": "2026-04-02T15:30:00+02:00"}},
    ]}
    with patch("urllib.request.urlopen", return_value=_mock_response(events)):
        slots = client.get_free_slots(date="2026-04-02", business_start=9, business_end=17)
    assert isinstance(slots, list)
    assert len(slots) > 0


def test_google_no_token_returns_empty():
    from integrations.google_calendar import GoogleCalendarClient
    client = GoogleCalendarClient(access_token=None)
    slots = client.get_free_slots()
    assert slots == []


def test_google_is_busy():
    from integrations.google_calendar import GoogleCalendarClient
    client = GoogleCalendarClient(access_token="test_token")
    freebusy = {"calendars": {"primary": {"busy": [
        {"start": "2026-04-02T10:00:00+02:00", "end": "2026-04-02T11:00:00+02:00"}
    ]}}}
    with patch("urllib.request.urlopen", return_value=_mock_response(freebusy)):
        result = client.is_busy_now()
    assert isinstance(result, bool)
