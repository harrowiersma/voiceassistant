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


def test_availability_page_has_form(client):
    response = client.get("/availability")
    html = response.data.decode()
    assert 'name="availability.manual_override"' in html
    assert 'name="availability.business_hours_start"' in html
    assert 'name="availability.business_hours_end"' in html


def test_availability_has_presence_mapping(client):
    response = client.get("/availability")
    html = response.data.decode()
    assert "Available" in html
    assert "Busy" in html
    assert "Do Not Disturb" in html


def test_availability_has_graph_section(client):
    response = client.get("/availability")
    html = response.data.decode()
    assert 'name="graph.client_id"' in html


def test_availability_save(client):
    response = client.post("/availability/save", data={
        "availability.manual_override": "auto",
        "availability.business_hours_start": "09:00",
        "availability.business_hours_end": "17:00",
        "availability.action_available": "forward",
        "availability.action_busy": "take_message",
        "availability.action_dnd": "take_message",
        "availability.action_away": "take_message",
        "graph.client_id": "",
        "graph.client_secret": "",
        "graph.tenant_id": "",
    }, follow_redirects=True)
    assert response.status_code == 200


def test_availability_persists(client):
    db_path = client.application.config["_DB_PATH"]
    client.post("/availability/save", data={
        "availability.manual_override": "unavailable",
        "availability.business_hours_start": "08:00",
        "availability.business_hours_end": "18:00",
        "availability.action_available": "forward",
        "availability.action_busy": "take_message",
        "availability.action_dnd": "take_message",
        "availability.action_away": "take_message",
        "graph.client_id": "abc123",
        "graph.client_secret": "secret",
        "graph.tenant_id": "tenant",
    })
    assert get_config("availability.manual_override", db_path=db_path) == "unavailable"
    assert get_config("availability.business_hours_start", db_path=db_path) == "08:00"
    assert get_config("graph.client_id", db_path=db_path) == "abc123"
