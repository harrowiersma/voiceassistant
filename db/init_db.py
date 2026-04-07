import sqlite3
import os

import bcrypt

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")
DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "instance", "voice_secretary.db"
)


def init_db(db_path=None):
    if db_path is None:
        db_path = DEFAULT_DB_PATH
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())

    # Migrate oauth_tokens: add person_id column if missing (v2 schema)
    cursor = conn.execute("PRAGMA table_info(oauth_tokens)")
    columns = [row[1] for row in cursor.fetchall()]
    if "person_id" not in columns:
        conn.execute("ALTER TABLE oauth_tokens ADD COLUMN person_id INTEGER NOT NULL DEFAULT 0")
        conn.commit()

    # Create default admin user if no users exist
    cursor = conn.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        pw_hash = bcrypt.hashpw(b"voicesec", bcrypt.gensalt()).decode()
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            ("admin", pw_hash),
        )
        conn.commit()

    # Create default persona if none exist
    cursor = conn.execute("SELECT COUNT(*) FROM personas")
    if cursor.fetchone()[0] == 0:
        conn.execute(
            "INSERT INTO personas (name, company_name, greeting, personality, unavailable_message, is_default, calendar_type) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("Default", "", "Hello, how may I help you?", "Professional and friendly.", "They are not available right now.", True, "none"),
        )
        conn.commit()

    conn.close()
