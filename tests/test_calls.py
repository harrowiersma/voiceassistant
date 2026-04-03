import json
import os
import tempfile
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
