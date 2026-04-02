import tempfile, os, pytest
from app import create_app

@pytest.fixture
def client():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app({"TESTING": True, "DATABASE": db_path})
    yield app.test_client()
    os.unlink(db_path)

def test_system_page_has_service_controls(client):
    response = client.get("/system")
    html = response.data.decode()
    assert "Asterisk" in html
    assert "Ollama" in html
    assert "Voice Secretary" in html

def test_system_page_has_health_section(client):
    response = client.get("/system")
    html = response.data.decode()
    assert "System" in html
    assert response.status_code == 200
