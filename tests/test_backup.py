import tempfile, os, json, pytest
from app import create_app
from app.helpers import set_config, get_config
from db.connection import get_db_connection

@pytest.fixture
def client():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app({"TESTING": True, "DATABASE": db_path})
    app.config["_DB_PATH"] = db_path
    yield app.test_client()
    os.unlink(db_path)

def test_backup_returns_json(client):
    db_path = client.application.config["_DB_PATH"]
    set_config("persona.company_name", "TestCo", "persona", db_path)
    response = client.get("/api/backup")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert "config" in data
    assert "knowledge_rules" in data
    assert any(c["key"] == "persona.company_name" for c in data["config"])

def test_restore_from_json(client):
    db_path = client.application.config["_DB_PATH"]
    backup = {
        "config": [
            {"key": "persona.company_name", "value": "Restored Co", "category": "persona"},
        ],
        "knowledge_rules": [
            {"rule_type": "info", "trigger_keywords": "address", "response": "123 Restored St.", "priority": 0, "enabled": True},
        ],
    }
    response = client.post("/api/restore", data=json.dumps(backup), content_type="application/json")
    assert response.status_code == 200
    assert get_config("persona.company_name", db_path=db_path) == "Restored Co"
