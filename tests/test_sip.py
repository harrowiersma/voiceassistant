import tempfile
import os
import pytest
from app import create_app
from app.helpers import get_config, set_config


@pytest.fixture
def client():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app({"TESTING": True, "DATABASE": db_path})
    app.config["_DB_PATH"] = db_path
    yield app.test_client()
    os.unlink(db_path)


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    from db.init_db import init_db

    init_db(path)
    yield path
    os.unlink(path)


def test_sip_page_has_form(client):
    """GET /sip has form fields for SIP configuration."""
    response = client.get("/sip")
    assert response.status_code == 200
    html = response.data.decode()
    for field in [
        "sip.inbound_server",
        "sip.inbound_username",
        "sip.inbound_password",
        "sip.inbound_port",
        "sip.forward_number",
    ]:
        assert f'name="{field}"' in html, f"Missing form field: {field}"


def test_sip_save_inbound(client):
    """POST /sip/save with valid data returns 200 after redirect."""
    response = client.post(
        "/sip/save",
        data={
            "sip.inbound_server": "sip.example.com",
            "sip.inbound_username": "user1",
            "sip.inbound_password": "pass1",
            "sip.inbound_port": "5060",
            "sip.forward_number": "+31612345678",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"saved" in response.data.lower() or b"SIP" in response.data


def test_sip_save_persists_to_db(client):
    """After POST, values are in DB via get_config()."""
    client.post(
        "/sip/save",
        data={
            "sip.inbound_server": "sip.example.com",
            "sip.inbound_username": "user1",
            "sip.inbound_password": "secret",
            "sip.inbound_port": "5060",
            "sip.forward_number": "+31612345678",
        },
        follow_redirects=True,
    )
    db = client.application.config["_DB_PATH"]
    assert get_config("sip.inbound_server", db_path=db) == "sip.example.com"
    assert get_config("sip.inbound_username", db_path=db) == "user1"
    assert get_config("sip.inbound_password", db_path=db) == "secret"
    assert get_config("sip.inbound_port", db_path=db) == "5060"
    assert get_config("sip.forward_number", db_path=db) == "+31612345678"


def test_sip_form_prefills_saved_values(client):
    """After saving, GET /sip shows saved values in form."""
    client.post(
        "/sip/save",
        data={
            "sip.inbound_server": "trunk.provider.com",
            "sip.inbound_username": "myuser",
            "sip.inbound_password": "mypass",
            "sip.inbound_port": "5061",
            "sip.forward_number": "+31687654321",
        },
        follow_redirects=True,
    )
    response = client.get("/sip")
    html = response.data.decode()
    assert "trunk.provider.com" in html
    assert "myuser" in html
    assert "mypass" in html
    assert "5061" in html
    assert "+31687654321" in html


def test_sip_outbound_optional(client):
    """POST without outbound fields works fine."""
    response = client.post(
        "/sip/save",
        data={
            "sip.inbound_server": "sip.example.com",
            "sip.inbound_username": "user1",
            "sip.inbound_password": "pass1",
            "sip.inbound_port": "5060",
            "sip.forward_number": "+31612345678",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    db = client.application.config["_DB_PATH"]
    # Outbound fields should be empty strings
    assert get_config("sip.outbound_server", db_path=db) == ""
    assert get_config("sip.outbound_username", db_path=db) == ""
    assert get_config("sip.outbound_password", db_path=db) == ""
    assert get_config("sip.outbound_port", db_path=db) == ""


def test_asterisk_config_generation(db_path):
    """render_pjsip_conf and render_extensions_conf produce correct output."""
    from config.asterisk_gen import render_pjsip_conf, render_extensions_conf

    cfg = {
        "sip.inbound_server": "sip.provider.com",
        "sip.inbound_username": "user1",
        "sip.inbound_password": "secret",
        "sip.inbound_port": "5060",
        "sip.outbound_server": "",
        "sip.outbound_username": "",
        "sip.outbound_password": "",
        "sip.outbound_port": "",
        "sip.forward_number": "+31612345678",
    }

    pjsip = render_pjsip_conf(cfg)
    assert "sip.provider.com" in pjsip
    assert "user1" in pjsip
    assert "secret" in pjsip
    assert "5060" in pjsip
    # No outbound trunk section when outbound_server is empty
    assert "[outbound-reg]" not in pjsip
    assert "[outbound-endpoint]" not in pjsip

    extensions = render_extensions_conf(cfg)
    assert "[inbound]" in extensions
    assert "127.0.0.1:9092" in extensions
    assert "+31612345678" in extensions

    # Now test with outbound configured
    cfg["sip.outbound_server"] = "out.provider.com"
    cfg["sip.outbound_username"] = "outuser"
    cfg["sip.outbound_password"] = "outsecret"
    cfg["sip.outbound_port"] = "5080"

    pjsip_with_outbound = render_pjsip_conf(cfg)
    assert "out.provider.com" in pjsip_with_outbound
    assert "outuser" in pjsip_with_outbound

    extensions_with_outbound = render_extensions_conf(cfg)
    assert "[outbound]" in extensions_with_outbound
