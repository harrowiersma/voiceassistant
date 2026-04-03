import tempfile, os, pytest
from db.init_db import init_db
from db.connection import get_db_connection


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    os.unlink(path)


def test_personas_table_exists(db_path):
    conn = get_db_connection(db_path)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='personas'")
    assert cursor.fetchone() is not None
    conn.close()


def test_default_persona_created(db_path):
    conn = get_db_connection(db_path)
    row = conn.execute("SELECT * FROM personas WHERE is_default = 1").fetchone()
    conn.close()
    assert row is not None
    assert row["name"] == "Default"


def test_create_persona(db_path):
    conn = get_db_connection(db_path)
    conn.execute(
        "INSERT INTO personas (name, company_name, greeting, personality, unavailable_message, calendar_type) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("Sales", "Wiersma Sales", "Hello, sales.", "Friendly.", "Sales closed.", "google"),
    )
    conn.commit()
    personas = conn.execute("SELECT * FROM personas ORDER BY id").fetchall()
    conn.close()
    assert len(personas) == 2


def test_knowledge_rules_have_persona_id(db_path):
    conn = get_db_connection(db_path)
    info = conn.execute("PRAGMA table_info(knowledge_rules)").fetchall()
    columns = [row["name"] for row in info]
    conn.close()
    assert "persona_id" in columns


def test_calls_have_persona_id(db_path):
    conn = get_db_connection(db_path)
    info = conn.execute("PRAGMA table_info(calls)").fetchall()
    columns = [row["name"] for row in info]
    conn.close()
    assert "persona_id" in columns
