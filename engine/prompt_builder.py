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

    lines = [
        f"You are a virtual secretary for {company}.",
        f"Personality: {personality}",
        f"Greeting (say this first): {greeting}",
        "",
        "## Conversation Flow (follow this order):",
        "1. Greet the caller with the greeting above.",
        "2. Ask the caller their name and the reason for their call.",
        "3. Once you know why they're calling, say: \"Let me check if they're available for you.\"",
        "4. Use the check_availability tool to check their status.",
        "5. If AVAILABLE: Say \"They're available. Let me connect you now, one moment please.\" Then use forward_call.",
        "6. If UNAVAILABLE: Say something like: \"" + unavailable + "\" Then ask if they'd like to leave a message.",
        "7. If they want to leave a message, use take_message with their name and reason.",
        "8. If they want a callback, use suggest_callback_times to offer available times.",
        "9. Always end politely: \"Thank you for calling {company}. Have a great day!\"",
        "",
        "## Important:",
        "- Always narrate what you're doing: \"Let me check...\", \"I'm connecting you now...\", \"I'll make sure they get your message.\"",
        "- Be conversational and warm, not robotic.",
        "- If the forward fails or nobody answers, apologize and offer to take a message instead.",
    ]

    if code_word:
        lines.append("")
        lines.append("## Secret Code Word:")
        lines.append(f"- If the caller says the code word \"{code_word}\" at any point during the conversation, "
                     "IMMEDIATELY skip the availability check and connect them. "
                     "Say: \"Of course, I'll connect you right away.\" Then use forward_call.")
        lines.append("- Do NOT reveal the code word or hint that one exists. If someone asks, say you don't know what they mean.")

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
        f"You are a virtual secretary for {company}.",
        f"Personality: {persona['personality']}",
        f"Greeting (say this first): {greeting}",
        "",
        "## Conversation Flow (follow this order):",
        "1. Greet the caller with the greeting above.",
        "2. Ask the caller their name and the reason for their call.",
        "3. Once you know why they're calling, say: \"Let me check if they're available for you.\"",
        "4. Use the check_availability tool to check their status.",
        f"5. If AVAILABLE: Say \"They're available. Let me connect you now, one moment please.\" Then use forward_call.",
        f"6. If UNAVAILABLE: Say something like: \"{unavailable}\" Then ask if they'd like to leave a message.",
        "7. If they want to leave a message, use take_message with their name and reason.",
        "8. If they want a callback, use suggest_callback_times to offer available times.",
        f"9. Always end politely: \"Thank you for calling {company}. Have a great day!\"",
        "",
        "## Important:",
        "- Always narrate what you're doing: \"Let me check...\", \"I'm connecting you now...\", \"I'll make sure they get your message.\"",
        "- Be conversational and warm, not robotic.",
        "- If the forward fails or nobody answers, apologize and offer to take a message instead.",
    ]

    if code_word:
        prompt_parts.append("")
        prompt_parts.append("## Secret Code Word:")
        prompt_parts.append(f"- If the caller says the code word \"{code_word}\" at any point during the conversation, "
                            "IMMEDIATELY skip the availability check and connect them. "
                            "Say: \"Of course, I'll connect you right away.\" Then use forward_call.")
        prompt_parts.append("- Do NOT reveal the code word or hint that one exists.")
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
