# tests/test_knowledge_persona.py
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


def test_knowledge_page_has_persona_filter(client):
    response = client.get("/knowledge")
    html = response.data.decode()
    assert "persona" in html.lower()


def test_add_rule_with_persona_id(client):
    response = client.post("/knowledge/add", data={
        "rule_type": "info", "trigger_keywords": "sales",
        "response": "Contact sales.", "active_from": "", "active_until": "",
        "priority": "0", "persona_id": "1",
    }, follow_redirects=True)
    assert response.status_code == 200


def test_api_rules_filter_by_persona(client):
    db_path = client.application.config["_DB_PATH"]
    conn = get_db_connection(db_path)
    conn.execute(
        "INSERT INTO knowledge_rules (rule_type, response, persona_id, enabled) VALUES (?, ?, ?, ?)",
        ("info", "Global rule.", None, True),
    )
    conn.execute(
        "INSERT INTO knowledge_rules (rule_type, response, persona_id, enabled) VALUES (?, ?, ?, ?)",
        ("info", "Persona 1 rule.", 1, True),
    )
    conn.commit()
    conn.close()
    response = client.get("/api/knowledge/rules?persona_id=1")
    data = json.loads(response.data)
    # Should include both global (persona_id IS NULL) and persona-specific rules
    assert len(data["rules"]) == 2
