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


def test_persona_page_has_form(client):
    response = client.get("/persona")
    html = response.data.decode()
    assert 'name="persona.company_name"' in html
    assert 'name="persona.greeting"' in html
    assert 'name="persona.personality"' in html
    assert 'name="persona.unavailable_message"' in html


def test_persona_save(client):
    response = client.post("/persona/save", data={
        "persona.company_name": "Wiersma Consulting",
        "persona.greeting": "Hello, you've reached Wiersma Consulting.",
        "persona.personality": "Professional, friendly.",
        "persona.unavailable_message": "Not available, may I take a message?",
    }, follow_redirects=True)
    assert response.status_code == 200


def test_persona_persists(client):
    db_path = client.application.config["_DB_PATH"]
    client.post("/persona/save", data={
        "persona.company_name": "Wiersma Consulting",
        "persona.greeting": "Hello from Wiersma!",
        "persona.personality": "Friendly",
        "persona.unavailable_message": "Not available",
    })
    assert get_config("persona.company_name", db_path=db_path) == "Wiersma Consulting"
    assert get_config("persona.greeting", db_path=db_path) == "Hello from Wiersma!"


def test_persona_prefills(client):
    client.post("/persona/save", data={
        "persona.company_name": "TestCo",
        "persona.greeting": "Hello TestCo",
        "persona.personality": "Warm",
        "persona.unavailable_message": "Sorry",
    })
    response = client.get("/persona")
    html = response.data.decode()
    assert "TestCo" in html
    assert "Hello TestCo" in html
