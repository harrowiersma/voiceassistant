import tempfile
import os
import pytest
from app import create_app


@pytest.fixture
def app():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    test_app = create_app({"TESTING": True, "DATABASE": db_path})
    yield test_app
    os.unlink(db_path)


@pytest.fixture
def client(app):
    return app.test_client()


def test_app_creates(app):
    assert app is not None
    assert app.config["TESTING"] is True


def test_home_page_returns_200(client):
    response = client.get("/")
    assert response.status_code == 200


def test_home_page_contains_title(client):
    response = client.get("/")
    assert b"Voice Secretary" in response.data
