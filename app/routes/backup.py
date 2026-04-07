from flask import Blueprint, jsonify, request, current_app
from db.connection import get_db_connection

bp = Blueprint("backup", __name__, url_prefix="/api")


@bp.route("/backup")
def backup():
    db_path = current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")
    conn = get_db_connection(db_path)

    config_rows = conn.execute("SELECT key, value, category FROM config ORDER BY key").fetchall()
    rules_rows = conn.execute(
        "SELECT rule_type, trigger_keywords, response, priority, enabled, "
        "active_from, active_until, persona_id FROM knowledge_rules ORDER BY id"
    ).fetchall()
    personas_rows = conn.execute(
        "SELECT name, company_name, greeting, personality, unavailable_message, "
        "calendar_type, inbound_number, is_default, enabled FROM personas ORDER BY id"
    ).fetchall()
    users_rows = conn.execute(
        "SELECT username, password_hash, role FROM users ORDER BY id"
    ).fetchall()
    blocked_rows = conn.execute(
        "SELECT pattern, block_type, reason FROM blocked_numbers ORDER BY id"
    ).fetchall()
    conn.close()

    return jsonify({
        "config": [dict(r) for r in config_rows],
        "knowledge_rules": [dict(r) for r in rules_rows],
        "personas": [dict(r) for r in personas_rows],
        "users": [dict(r) for r in users_rows],
        "blocked_numbers": [dict(r) for r in blocked_rows],
    })


@bp.route("/restore", methods=["POST"])
def restore():
    data = request.get_json(force=True)
    db_path = current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")
    conn = get_db_connection(db_path)

    for item in data.get("config", []):
        conn.execute(
            "INSERT INTO config (key, value, category) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
            (item["key"], item["value"], item.get("category")),
        )

    for rule in data.get("knowledge_rules", []):
        conn.execute(
            "INSERT INTO knowledge_rules (rule_type, trigger_keywords, response, priority, enabled, "
            "active_from, active_until, persona_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (rule["rule_type"], rule.get("trigger_keywords"), rule["response"],
             rule.get("priority", 0), rule.get("enabled", True),
             rule.get("active_from"), rule.get("active_until"), rule.get("persona_id")),
        )

    for persona in data.get("personas", []):
        conn.execute(
            "INSERT INTO personas (name, company_name, greeting, personality, unavailable_message, "
            "calendar_type, inbound_number, is_default, enabled) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET company_name=excluded.company_name, "
            "greeting=excluded.greeting, personality=excluded.personality, "
            "unavailable_message=excluded.unavailable_message, calendar_type=excluded.calendar_type, "
            "inbound_number=excluded.inbound_number",
            (persona["name"], persona.get("company_name"), persona.get("greeting"),
             persona.get("personality"), persona.get("unavailable_message"),
             persona.get("calendar_type", "none"), persona.get("inbound_number"),
             persona.get("is_default", False), persona.get("enabled", True)),
        )

    for user in data.get("users", []):
        conn.execute(
            "INSERT OR IGNORE INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (user["username"], user["password_hash"], user.get("role", "admin")),
        )

    for block in data.get("blocked_numbers", []):
        conn.execute(
            "INSERT INTO blocked_numbers (pattern, block_type, reason) VALUES (?, ?, ?)",
            (block["pattern"], block.get("block_type", "exact"), block.get("reason")),
        )

    conn.commit()
    conn.close()

    return jsonify({"status": "restored"})
