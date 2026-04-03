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


def test_blocking_page_loads(client):
    response = client.get("/blocking")
    assert response.status_code == 200
    assert b"Call Blocking" in response.data


def test_add_blocked_number(client):
    response = client.post("/blocking/add", data={
        "pattern": "+41791234567", "block_type": "exact", "reason": "Spam caller",
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b"+41791234567" in response.data


def test_add_blocked_prefix(client):
    response = client.post("/blocking/add", data={
        "pattern": "+234", "block_type": "prefix", "reason": "Country block",
    }, follow_redirects=True)
    assert response.status_code == 200


def test_check_number_blocked_exact(client):
    client.post("/blocking/add", data={"pattern": "+41791234567", "block_type": "exact", "reason": "Spam"})
    response = client.get("/api/blocking/check?number=%2B41791234567")
    data = json.loads(response.data)
    assert data["blocked"] is True


def test_check_number_blocked_prefix(client):
    client.post("/blocking/add", data={"pattern": "+234", "block_type": "prefix", "reason": "Country"})
    response = client.get("/api/blocking/check?number=%2B2341234567")
    data = json.loads(response.data)
    assert data["blocked"] is True


def test_check_number_not_blocked(client):
    response = client.get("/api/blocking/check?number=%2B41791111111")
    data = json.loads(response.data)
    assert data["blocked"] is False


def test_delete_blocked_number(client):
    client.post("/blocking/add", data={"pattern": "+41791234567", "block_type": "exact", "reason": "Test"})
    response = client.post("/blocking/1/delete", follow_redirects=True)
    assert response.status_code == 200
