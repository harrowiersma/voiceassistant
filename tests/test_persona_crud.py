import tempfile, os, json, pytest
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


def test_personas_list_page(client):
    response = client.get("/personas")
    assert response.status_code == 200
    assert b"Personas" in response.data
    assert b"Default" in response.data


def test_create_persona(client):
    response = client.post("/personas/add", data={
        "name": "Sales Team", "company_name": "Wiersma Sales",
        "greeting": "Hello, sales.", "personality": "Enthusiastic.",
        "unavailable_message": "Sales closed.",
        "calendar_type": "google", "inbound_number": "+41441234567",
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b"Sales Team" in response.data


def test_edit_persona(client):
    client.post("/personas/add", data={
        "name": "Finance", "company_name": "Finance Dept",
        "greeting": "Hello.", "personality": "Precise.",
        "unavailable_message": "Closed.", "calendar_type": "none", "inbound_number": "",
    })
    # Find the persona id (should be 2, since Default is 1)
    response = client.post("/personas/2/edit", data={
        "name": "Finance Updated", "company_name": "Finance Updated",
        "greeting": "Hello finance.", "personality": "Precise.",
        "unavailable_message": "Closed.", "calendar_type": "msgraph", "inbound_number": "+41442222222",
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b"Finance Updated" in response.data


def test_delete_persona(client):
    client.post("/personas/add", data={
        "name": "Temp", "company_name": "Temp",
        "greeting": "Hi.", "personality": ".", "unavailable_message": ".",
        "calendar_type": "none", "inbound_number": "",
    })
    response = client.post("/personas/2/delete", follow_redirects=True)
    assert response.status_code == 200


def test_cannot_delete_default_persona(client):
    response = client.post("/personas/1/delete", follow_redirects=True)
    assert response.status_code == 200
    assert b"Default" in response.data  # Still exists


def test_personas_api_list(client):
    response = client.get("/api/personas")
    data = json.loads(response.data)
    assert len(data["personas"]) >= 1
    assert data["personas"][0]["name"] == "Default"
