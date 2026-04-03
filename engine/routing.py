"""Team/department routing — resolve persona by inbound phone number."""

from db.connection import get_db_connection


def resolve_persona(inbound_number, db_path=None):
    """Look up the persona matching *inbound_number*.

    Falls back to the default persona if no match is found.
    Returns a dict of persona columns, or None if nothing at all.
    """
    conn = get_db_connection(db_path)
    persona = conn.execute(
        "SELECT * FROM personas WHERE inbound_number = ? AND enabled = 1",
        (inbound_number,),
    ).fetchone()
    if not persona:
        persona = conn.execute(
            "SELECT * FROM personas WHERE is_default = 1",
        ).fetchone()
    conn.close()
    return dict(persona) if persona else None
