import tempfile, os, pytest
from app import create_app
from app.helpers import get_config, set_config


@pytest.fixture
def client():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app({"TESTING": True, "DATABASE": db_path})
    app.config["_DB_PATH"] = db_path
    app.config["ASTERISK_CONFIG_DIR"] = tempfile.mkdtemp()
    yield app.test_client()
    os.unlink(db_path)


def test_sip_page_has_extensions_section(client):
    response = client.get("/sip")
    html = response.data.decode()
    assert 'name="sip.extension_1_name"' in html
    assert 'name="sip.extension_1_password"' in html


def test_sip_save_with_extension(client):
    response = client.post("/sip/save", data={
        "sip.inbound_server": "sip.example.com",
        "sip.inbound_username": "user123",
        "sip.inbound_password": "pass456",
        "sip.inbound_port": "5060",
        "sip.forward_number": "+41791234567",
        "sip.extension_1_name": "desk-phone",
        "sip.extension_1_password": "ext-pass-1",
        "sip.extension_2_name": "",
        "sip.extension_2_password": "",
        "sip.extension_3_name": "",
        "sip.extension_3_password": "",
    }, follow_redirects=True)
    assert response.status_code == 200
    db_path = client.application.config["_DB_PATH"]
    assert get_config("sip.extension_1_name", db_path=db_path) == "desk-phone"


def test_asterisk_config_with_extension(client):
    from config.asterisk_gen import render_pjsip_conf, render_extensions_conf
    config = {
        "sip.inbound_server": "sip.example.com",
        "sip.inbound_username": "user123",
        "sip.inbound_password": "pass456",
        "sip.inbound_port": "5060",
        "sip.forward_number": "+41791234567",
        "sip.extension_1_name": "desk-phone",
        "sip.extension_1_password": "ext-pass-1",
    }
    pjsip = render_pjsip_conf(config)
    assert "desk-phone" in pjsip
    extensions = render_extensions_conf(config)
    assert "desk-phone" in extensions
    assert "+41791234567" in extensions


def test_apply_config_generates_files(client):
    db_path = client.application.config["_DB_PATH"]
    config_dir = client.application.config["ASTERISK_CONFIG_DIR"]
    set_config("sip.inbound_server", "sip.example.com", "sip", db_path)
    set_config("sip.inbound_username", "user", "sip", db_path)
    set_config("sip.inbound_password", "pass", "sip", db_path)
    set_config("sip.inbound_port", "5060", "sip", db_path)
    set_config("sip.forward_number", "+41791234567", "sip", db_path)
    response = client.post("/sip/apply", follow_redirects=True)
    assert response.status_code == 200
    assert os.path.exists(os.path.join(config_dir, "pjsip.conf"))
    assert os.path.exists(os.path.join(config_dir, "extensions.conf"))
    with open(os.path.join(config_dir, "pjsip.conf")) as f:
        assert "sip.example.com" in f.read()


def test_apply_without_config_still_succeeds(client):
    # No SIP config set — should still generate (empty) files without crashing
    response = client.post("/sip/apply", follow_redirects=True)
    assert response.status_code == 200
