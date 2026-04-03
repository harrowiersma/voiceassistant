from flask import Blueprint, jsonify, request, current_app
from db.connection import get_db_connection

bp = Blueprint("backup", __name__, url_prefix="/api")


@bp.route("/backup")
def backup():
    db_path = current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")
    conn = get_db_connection(db_path)

    config_rows = conn.execute("SELECT key, value, category FROM config ORDER BY key").fetchall()
    rules_rows = conn.execute(
        "SELECT rule_type, trigger_keywords, response, priority, enabled FROM knowledge_rules ORDER BY id"
    ).fetchall()
    conn.close()

    return jsonify({
        "config": [dict(r) for r in config_rows],
        "knowledge_rules": [dict(r) for r in rules_rows],
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
            (item["key"], item["value"], item["category"]),
        )

    for rule in data.get("knowledge_rules", []):
        conn.execute(
            "INSERT INTO knowledge_rules (rule_type, trigger_keywords, response, priority, enabled) "
            "VALUES (?, ?, ?, ?, ?)",
            (rule["rule_type"], rule.get("trigger_keywords"), rule["response"],
             rule.get("priority", 0), rule.get("enabled", True)),
        )

    conn.commit()
    conn.close()

    return jsonify({"status": "restored"})
