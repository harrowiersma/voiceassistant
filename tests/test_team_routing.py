"""Tests for team/department routing — persona resolution by inbound number."""
import tempfile
import os
import pytest

from db.init_db import init_db
from db.connection import get_db_connection


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    os.unlink(path)


def test_resolve_persona_by_inbound_number(db_path):
    from engine.routing import resolve_persona
    conn = get_db_connection(db_path)
    conn.execute(
        "INSERT INTO personas (name, company_name, greeting, personality, unavailable_message, inbound_number, calendar_type) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("Sales", "Wiersma Sales", "Hello sales.", "Friendly.", "Sales closed.", "+41441234567", "none"),
    )
    conn.commit()
    conn.close()
    persona = resolve_persona("+41441234567", db_path)
    assert persona is not None
    assert persona["name"] == "Sales"


def test_resolve_persona_falls_back_to_default(db_path):
    from engine.routing import resolve_persona
    persona = resolve_persona("+41449999999", db_path)
    assert persona is not None
    assert persona["is_default"] == 1


def test_build_prompt_for_persona(db_path):
    from engine.prompt_builder import build_system_prompt_for_persona
    conn = get_db_connection(db_path)
    conn.execute(
        "INSERT INTO personas (name, company_name, greeting, personality, unavailable_message, calendar_type) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("Finance", "Wiersma Finance", "Hello finance.", "Precise.", "Finance closed.", "none"),
    )
    conn.commit()
    conn.execute(
        "INSERT INTO knowledge_rules (rule_type, trigger_keywords, response, persona_id, enabled) "
        "VALUES (?, ?, ?, ?, ?)",
        ("info", "invoice", "Please email invoices@wiersma.com", 2, True),
    )
    conn.commit()
    conn.close()
    prompt = build_system_prompt_for_persona(persona_id=2, db_path=db_path)
    assert "Wiersma Finance" in prompt
    assert "invoice" in prompt.lower()
