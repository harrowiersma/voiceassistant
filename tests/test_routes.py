import tempfile
import os
import pytest
from app import create_app


@pytest.fixture
def client():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app({"TESTING": True, "DATABASE": db_path})
    yield app.test_client()
    os.unlink(db_path)


ROUTES = [
    ("/", 200, "Home"),
    ("/sip", 200, "SIP Settings"),
    ("/ai", 200, "AI Settings"),
    ("/persona", 200, "Persona"),
    ("/knowledge", 200, "Knowledge Base"),
    ("/availability", 200, "Availability"),
    ("/calls", 200, "Call Log"),
    ("/actions", 200, "Actions"),
    ("/system", 200, "System"),
]


@pytest.mark.parametrize("path,expected_status,expected_text", ROUTES)
def test_route_returns_200_with_title(client, path, expected_status, expected_text):
    response = client.get(path)
    assert response.status_code == expected_status
    assert expected_text.encode() in response.data
