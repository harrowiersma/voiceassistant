"""Assembles the LLM system prompt from persona config + active knowledge rules."""

from datetime import date

from app.helpers import get_config
from db.connection import get_db_connection


def _get_active_rules(db_path=None):
    """Return enabled knowledge rules whose date range includes today, ordered by priority DESC."""
    today = date.today().isoformat()
    conn = get_db_connection(db_path)
    rows = conn.execute(
        """
        SELECT rule_type, trigger_keywords, response, priority
        FROM knowledge_rules
        WHERE enabled = 1
          AND (active_from IS NULL OR active_from <= ?)
          AND (active_until IS NULL OR active_until >= ?)
        ORDER BY priority DESC
        """,
        (today, today),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def build_system_prompt(db_path=None):
    """Build the full system prompt from persona config and active knowledge rules."""
    company = get_config("persona.company_name", "the company", db_path)
    personality = get_config("persona.personality", "Professional.", db_path)
    greeting_template = get_config("persona.greeting", "Hello.", db_path)
    unavailable = get_config("persona.unavailable_message", "They are not available.", db_path)

    greeting = greeting_template.replace("{company}", company)

    lines = [
        f"You are a virtual secretary for {company}.",
        f"Personality: {personality}",
        f"Greeting (say this first): {greeting}",
        f"When the person is unavailable, say: {unavailable}",
    ]

    rules = _get_active_rules(db_path)
    if rules:
        lines.append("")
        lines.append("## Knowledge Rules (follow these instructions):")
        for rule in rules:
            rule_type = rule["rule_type"].upper()
            keywords = rule["trigger_keywords"]
            response = rule["response"]
            if keywords:
                lines.append(f"- [{rule_type}] When caller mentions: {keywords}. {response}")
            else:
                lines.append(f"- [{rule_type}] {response}")

    return "\n".join(lines)


def get_active_vacation(db_path=None):
    """Return the highest-priority active vacation rule, or None."""
    today = date.today().isoformat()
    conn = get_db_connection(db_path)
    row = conn.execute(
        """
        SELECT id, rule_type, trigger_keywords, response, priority, active_from, active_until
        FROM knowledge_rules
        WHERE enabled = 1
          AND rule_type = 'vacation'
          AND (active_from IS NULL OR active_from <= ?)
          AND (active_until IS NULL OR active_until >= ?)
        ORDER BY priority DESC
        LIMIT 1
        """,
        (today, today),
    ).fetchone()
    conn.close()
    return dict(row) if row else None
