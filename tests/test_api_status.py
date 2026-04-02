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


def test_api_status_system_has_cpu_and_ram(client):
    response = client.get("/api/status")
    data = json.loads(response.data)
    system = data["system"]
    assert "cpu_temp" in system
    assert "ram_used_mb" in system
    assert "ram_total_mb" in system
    assert "disk_used_pct" in system
