"""Assembles the LLM system prompt from persona config + active knowledge rules."""

from datetime import date, datetime

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

    code_word = get_config("security.code_word", "", db_path)

    # Keep prompt SHORT for small models. Every token = latency on Pi.
    lines = [
        f"You are a phone secretary for {company}. This is a live phone call.",
        "RULES: Reply in 1-2 short sentences only. Be warm and professional.",
        "FLOW: Ask caller's name and reason. Then say you'll check availability. Then take a message or say goodbye.",
        f"When unavailable say: {unavailable}",
        "Never make up information. Never pretend to do things you cannot do.",
        "Do NOT use actions, emojis, stage directions, or narration like '(I press a button)'. Just speak naturally.",
    ]

    if code_word:
        lines.append(f"If caller says \"{code_word}\", say \"Connecting you now.\"")


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


def build_system_prompt_for_persona(persona_id, db_path=None):
    """Build system prompt from a specific persona's settings + persona-scoped knowledge rules."""
    conn = get_db_connection(db_path)
    persona = conn.execute("SELECT * FROM personas WHERE id = ?", (persona_id,)).fetchone()
    if not persona:
        conn.close()
        return build_system_prompt(db_path)  # Fall back to config-based prompt

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rules = conn.execute(
        """SELECT * FROM knowledge_rules
           WHERE enabled = 1 AND (persona_id = ? OR persona_id IS NULL)
             AND (active_from IS NULL OR active_from <= ?)
             AND (active_until IS NULL OR active_until >= ?)
           ORDER BY priority DESC, id""",
        (persona_id, now, now),
    ).fetchall()
    conn.close()

    company = persona["company_name"]
    greeting = persona["greeting"].replace("{company}", company)
    unavailable = persona["unavailable_message"]
    code_word = get_config("security.code_word", "", db_path)

    prompt_parts = [
        f"You are a phone secretary for {company}. This is a live phone call.",
        "RULES: Reply in 1-2 short sentences only. Be warm and professional.",
        "FLOW: Ask caller's name and reason. Then say you'll check availability. Then take a message or say goodbye.",
        f"When unavailable say: {unavailable}",
        "Never make up information. Never pretend to do things you cannot do.",
        "Do NOT use actions, emojis, stage directions, or narration. Just speak naturally.",
    ]

    if code_word:
        prompt_parts.append(f"If caller says \"{code_word}\", say \"Connecting you now.\"")

    if rules:
        prompt_parts.append("\n## Knowledge Rules (follow these instructions):")
        for rule in rules:
            rule_dict = dict(rule)
            rule_line = f"- [{rule_dict['rule_type'].upper()}]"
            if rule_dict["trigger_keywords"]:
                rule_line += f" When caller mentions: {rule_dict['trigger_keywords']}."
            rule_line += f" {rule_dict['response']}"
            prompt_parts.append(rule_line)
    return "\n".join(prompt_parts)
