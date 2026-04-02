import tempfile
import os
import json
import pytest
from app import create_app


@pytest.fixture
def client():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app({"TESTING": True, "DATABASE": db_path})
    yield app.test_client()
    os.unlink(db_path)


def test_api_status_returns_json(client):
    response = client.get("/api/status")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert "system" in data
    assert "asterisk" in data
    assert "ai" in data
    assert "graph" in data


def test_api_status_ai_section_has_all_fields(client):
    response = client.get("/api/status")
    data = json.loads(response.data)
    ai = data["ai"]
    assert "vosk" in ai
    assert "ollama" in ai
    assert "piper" in ai
    assert isinstance(ai["vosk"], str)
    assert isinstance(ai["ollama"], str)
    assert isinstance(ai["piper"], str)


def test_api_status_asterisk_section(client):
    response = client.get("/api/status")
    data = json.loads(response.data)
    ast = data["asterisk"]
    assert "status" in ast
    assert "active_calls" in ast
    assert isinstance(ast["active_calls"], int)


def test_api_status_system_has_cpu_and_ram(client):
    response = client.get("/api/status")
    data = json.loads(response.data)
    system = data["system"]
    assert "cpu_temp" in system
    assert "ram_used_mb" in system
    assert "ram_total_mb" in system
    assert "disk_used_pct" in system
