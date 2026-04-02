import sqlite3
from db.init_db import init_db
from db.connection import get_db_connection


def test_init_db_creates_tables(db_path):
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = [row[0] for row in cursor.fetchall()]
    conn.close()
    assert "config" in tables
    assert "calls" in tables
    assert "knowledge_rules" in tables
    assert "oauth_tokens" in tables
    assert "audit_log" in tables


def test_get_db_connection(db_path):
    init_db(db_path)
    conn = get_db_connection(db_path)
    assert conn is not None
    conn.execute("INSERT INTO config (key, value, category) VALUES (?, ?, ?)",
                 ("test.key", "test_value", "system"))
    conn.commit()
    row = conn.execute("SELECT value FROM config WHERE key = ?", ("test.key",)).fetchone()
    assert row["value"] == "test_value"
    conn.close()


def test_config_upsert(db_path):
    init_db(db_path)
    conn = get_db_connection(db_path)
    conn.execute(
        "INSERT INTO config (key, value, category) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
        ("persona.company_name", "Wiersma Consulting", "persona"),
    )
    conn.commit()
    # Update same key
    conn.execute(
        "INSERT INTO config (key, value, category) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
        ("persona.company_name", "Wiersma & Partners", "persona"),
    )
    conn.commit()
    row = conn.execute("SELECT value FROM config WHERE key = ?", ("persona.company_name",)).fetchone()
    assert row["value"] == "Wiersma & Partners"
    conn.close()
