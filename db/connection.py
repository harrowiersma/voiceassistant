import sqlite3

DEFAULT_DB_PATH = None  # Set by app factory


def get_db_connection(db_path=None):
    if db_path is None:
        from db.init_db import DEFAULT_DB_PATH
        db_path = DEFAULT_DB_PATH
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn
