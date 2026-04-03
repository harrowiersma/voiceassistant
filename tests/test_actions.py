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


def test_actions_page_has_smtp_form(client):
    response = client.get("/actions")
    html = response.data.decode()
    assert 'name="actions.smtp_server"' in html
    assert 'name="actions.smtp_port"' in html
    assert 'name="actions.smtp_username"' in html
    assert 'name="actions.email_to"' in html


def test_actions_page_has_notification_prefs(client):
    response = client.get("/actions")
    html = response.data.decode()
    assert 'name="actions.notify_on"' in html


def test_actions_save(client):
    response = client.post("/actions/save", data={
        "actions.smtp_server": "smtp.gmail.com",
        "actions.smtp_port": "587",
        "actions.smtp_username": "user@gmail.com",
        "actions.smtp_password": "app-password",
        "actions.email_to": "owner@gmail.com",
        "actions.email_from": "secretary@gmail.com",
        "actions.notify_on": "message_only",
    }, follow_redirects=True)
    assert response.status_code == 200


def test_actions_persists(client):
    db_path = client.application.config["_DB_PATH"]
    client.post("/actions/save", data={
        "actions.smtp_server": "smtp.gmail.com",
        "actions.smtp_port": "587",
        "actions.smtp_username": "user@gmail.com",
        "actions.smtp_password": "app-password",
        "actions.email_to": "owner@gmail.com",
        "actions.email_from": "secretary@gmail.com",
        "actions.notify_on": "all_calls",
    })
    assert get_config("actions.smtp_server", db_path=db_path) == "smtp.gmail.com"
    assert get_config("actions.notify_on", db_path=db_path) == "all_calls"
