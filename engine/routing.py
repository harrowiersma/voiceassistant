"""Team/department routing — resolve persona by inbound phone number."""

import logging

from db.connection import get_db_connection

logger = logging.getLogger(__name__)


def _normalize_number(num):
    """Strip +, leading zeros, spaces — keep only digits for comparison."""
    if not num:
        return ""
    return num.replace("+", "").replace(" ", "").replace("-", "").lstrip("0")


def resolve_persona(inbound_number, db_path=None):
    """Look up the persona matching *inbound_number*.

    Tries exact match first, then normalized (strip +/leading zeros).
    Falls back to the default persona if no match is found.
    Returns a dict of persona columns, or None if nothing at all.
    """
    conn = get_db_connection(db_path)

    # Exact match
    persona = conn.execute(
        "SELECT * FROM personas WHERE inbound_number = ? AND enabled = 1",
        (inbound_number,),
    ).fetchone()

    # Normalized / partial match (handles +41... vs 41... vs 0041...)
    all_personas = []
    if not persona and inbound_number:
        norm = _normalize_number(inbound_number)
        all_personas = conn.execute(
            "SELECT * FROM personas WHERE enabled = 1 AND inbound_number IS NOT NULL"
        ).fetchall()
        for p in all_personas:
            if _normalize_number(dict(p)["inbound_number"]) == norm:
                persona = p
                logger.info(f"Persona matched via normalized number: {inbound_number} -> {dict(p)['name']}")
                break

    # Partial match — DID might be a suffix of the stored number or vice versa
    if not persona and inbound_number:
        norm = _normalize_number(inbound_number)
        for p in all_personas:
            p_norm = _normalize_number(dict(p)["inbound_number"])
            if norm.endswith(p_norm[-8:]) or p_norm.endswith(norm[-8:]):
                persona = p
                logger.info(f"Persona matched via suffix: {inbound_number} -> {dict(p)['name']}")
                break

    if not persona:
        persona = conn.execute(
            "SELECT * FROM personas WHERE is_default = 1",
        ).fetchone()
        if persona:
            logger.info(f"No persona match for '{inbound_number}', using default: {dict(persona)['name']}")

    conn.close()
    return dict(persona) if persona else None
