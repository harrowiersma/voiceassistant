import tempfile, os, pytest
from app import create_app
from app.helpers import get_config


@pytest.fixture
def client():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app({"TESTING": True, "DATABASE": db_path})
    app.config["_DB_PATH"] = db_path
    yield app.test_client()
    os.unlink(db_path)


def test_ai_page_has_form(client):
    response = client.get("/ai")
    html = response.data.decode()
    assert 'name="ai.stt_model"' in html
    assert 'name="ai.llm_model"' in html
    assert 'name="ai.tts_voice"' in html
    assert 'name="ai.response_timeout"' in html
    assert 'name="ai.max_call_duration"' in html


def test_ai_save(client):
    response = client.post("/ai/save", data={
        "ai.stt_model": "vosk-small",
        "ai.llm_model": "llama3.2:1b",
        "ai.tts_voice": "en-us-amy-medium",
        "ai.response_timeout": "10",
        "ai.max_call_duration": "300",
    }, follow_redirects=True)
    assert response.status_code == 200


def test_ai_persists(client):
    db_path = client.application.config["_DB_PATH"]
    client.post("/ai/save", data={
        "ai.stt_model": "vosk-small",
        "ai.llm_model": "llama3.2:1b",
        "ai.tts_voice": "en-us-amy-medium",
        "ai.response_timeout": "10",
        "ai.max_call_duration": "300",
    })
    assert get_config("ai.llm_model", db_path=db_path) == "llama3.2:1b"
    assert get_config("ai.response_timeout", db_path=db_path) == "10"
