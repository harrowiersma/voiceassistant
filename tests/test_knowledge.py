import tempfile, os, json, pytest
from app import create_app


@pytest.fixture
def client():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app({"TESTING": True, "DATABASE": db_path})
    app.config["_DB_PATH"] = db_path
    yield app.test_client()
    os.unlink(db_path)


def test_knowledge_page_loads(client):
    response = client.get("/knowledge")
    assert response.status_code == 200
    assert b"Knowledge Base" in response.data


def test_knowledge_page_has_add_button(client):
    response = client.get("/knowledge")
    assert b"Add Rule" in response.data


def test_create_topic_rule(client):
    response = client.post("/knowledge/add", data={
        "rule_type": "topic", "trigger_keywords": "book, publication",
        "response": "You can find the book on Amazon.",
        "active_from": "", "active_until": "", "priority": "0",
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b"book" in response.data.lower()


def test_create_vacation_rule_with_dates(client):
    response = client.post("/knowledge/add", data={
        "rule_type": "vacation", "trigger_keywords": "",
        "response": "Our office is closed for the holidays.",
        "active_from": "2026-12-24", "active_until": "2027-01-02", "priority": "10",
    }, follow_redirects=True)
    assert response.status_code == 200


def test_create_rule_missing_response_fails(client):
    response = client.post("/knowledge/add", data={
        "rule_type": "topic", "trigger_keywords": "test",
        "response": "", "active_from": "", "active_until": "", "priority": "0",
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b"required" in response.data.lower() or b"error" in response.data.lower()


def test_toggle_rule(client):
    client.post("/knowledge/add", data={
        "rule_type": "info", "trigger_keywords": "address",
        "response": "123 Main St.", "active_from": "", "active_until": "", "priority": "0",
    })
    response = client.post("/knowledge/1/toggle", follow_redirects=True)
    assert response.status_code == 200


def test_delete_rule(client):
    client.post("/knowledge/add", data={
        "rule_type": "info", "trigger_keywords": "test",
        "response": "Test.", "active_from": "", "active_until": "", "priority": "0",
    })
    response = client.post("/knowledge/1/delete", follow_redirects=True)
    assert response.status_code == 200


def test_list_rules_api(client):
    client.post("/knowledge/add", data={
        "rule_type": "topic", "trigger_keywords": "book",
        "response": "Amazon link.", "active_from": "", "active_until": "", "priority": "0",
    })
    response = client.get("/api/knowledge/rules")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert len(data["rules"]) == 1
    assert data["rules"][0]["rule_type"] == "topic"
