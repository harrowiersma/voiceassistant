from db.connection import get_db_connection


def get_config(key, default=None, db_path=None):
    conn = get_db_connection(db_path)
    row = conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_config(key, value, category, db_path=None):
    conn = get_db_connection(db_path)
    conn.execute(
        "INSERT INTO config (key, value, category) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
        (key, value, category),
    )
    conn.commit()
    conn.close()


def get_configs_by_category(category, db_path=None):
    conn = get_db_connection(db_path)
    rows = conn.execute(
        "SELECT key, value, updated_at FROM config WHERE category = ? ORDER BY key",
        (category,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
