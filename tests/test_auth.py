# tests/test_auth.py
import tempfile, os, pytest
from app import create_app


@pytest.fixture
def client():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    # NOT setting TESTING=True so auth is enforced
    app = create_app({"DATABASE": db_path, "SECRET_KEY": "test-secret"})
    app.config["_DB_PATH"] = db_path
    yield app.test_client()
    os.unlink(db_path)


@pytest.fixture
def testing_client():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app({"TESTING": True, "DATABASE": db_path})
    yield app.test_client()
    os.unlink(db_path)


def test_unauthenticated_redirects_to_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_login_page_loads(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert b'name="username"' in response.data
    assert b'name="password"' in response.data


def test_login_with_default_credentials(client):
    response = client.post(
        "/login",
        data={"username": "admin", "password": "voicesec"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Voice Secretary" in response.data


def test_login_wrong_password(client):
    response = client.post(
        "/login",
        data={"username": "admin", "password": "wrong"},
        follow_redirects=True,
    )
    assert b"nvalid" in response.data  # "Invalid" case-insensitive partial match


def test_logout(client):
    client.post("/login", data={"username": "admin", "password": "voicesec"})
    response = client.get("/logout", follow_redirects=True)
    assert b'name="username"' in response.data  # Back to login page


def test_testing_mode_skips_auth(testing_client):
    response = testing_client.get("/")
    assert response.status_code == 200  # No redirect, auth skipped
