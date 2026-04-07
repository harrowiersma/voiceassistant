from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app
from db.connection import get_db_connection

bp = Blueprint("knowledge", __name__)


def _db_path():
    return current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")


@bp.route("/knowledge")
def index():
    conn = get_db_connection(_db_path())
    rules = conn.execute(
        "SELECT * FROM knowledge_rules ORDER BY priority DESC, id"
    ).fetchall()
    personas = conn.execute(
        "SELECT id, name FROM personas WHERE enabled = 1 ORDER BY is_default DESC, name"
    ).fetchall()
    conn.close()
    return render_template("knowledge.html", rules=rules, personas=personas)


@bp.route("/knowledge/add", methods=["POST"])
def add():
    response_text = request.form.get("response", "").strip()
    if not response_text:
        flash("Response is required.", "error")
        return redirect(url_for("knowledge.index"))

    rule_type = request.form.get("rule_type", "topic")
    trigger_keywords = request.form.get("trigger_keywords", "").strip()
    active_from = request.form.get("active_from", "").strip() or None
    active_until = request.form.get("active_until", "").strip() or None
    priority = int(request.form.get("priority", 0))
    persona_id_str = request.form.get("persona_id", "").strip()
    persona_id = int(persona_id_str) if persona_id_str else None

    conn = get_db_connection(_db_path())
    conn.execute(
        """INSERT INTO knowledge_rules
           (rule_type, trigger_keywords, response, active_from, active_until, priority, persona_id)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (rule_type, trigger_keywords, response_text, active_from, active_until, priority, persona_id),
    )
    conn.commit()
    conn.close()
    flash("Rule added.", "success")
    return redirect(url_for("knowledge.index"))


@bp.route("/knowledge/<int:rule_id>/edit", methods=["GET", "POST"])
def edit(rule_id):
    db = _db_path()
    conn = get_db_connection(db)

    if request.method == "POST":
        conn.execute(
            """UPDATE knowledge_rules SET rule_type=?, trigger_keywords=?, response=?,
               active_from=?, active_until=?, priority=?, persona_id=?, updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (
                request.form.get("rule_type", "topic"),
                request.form.get("trigger_keywords", "").strip(),
                request.form.get("response", "").strip(),
                request.form.get("active_from", "").strip() or None,
                request.form.get("active_until", "").strip() or None,
                int(request.form.get("priority", 0)),
                int(request.form["persona_id"]) if request.form.get("persona_id") else None,
                rule_id,
            ),
        )
        conn.commit()
        conn.close()
        flash("Rule updated.", "success")
        return redirect(url_for("knowledge.index"))

    rule = conn.execute("SELECT * FROM knowledge_rules WHERE id = ?", (rule_id,)).fetchone()
    personas = conn.execute(
        "SELECT id, name FROM personas WHERE enabled = 1 ORDER BY is_default DESC, name"
    ).fetchall()
    conn.close()
    if not rule:
        flash("Rule not found.", "error")
        return redirect(url_for("knowledge.index"))
    return render_template("knowledge_edit.html", rule=dict(rule), personas=personas)


@bp.route("/knowledge/<int:rule_id>/toggle", methods=["POST"])
def toggle(rule_id):
    conn = get_db_connection(_db_path())
    conn.execute(
        "UPDATE knowledge_rules SET enabled = NOT enabled, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (rule_id,),
    )
    conn.commit()
    conn.close()
    flash("Rule toggled.", "success")
    return redirect(url_for("knowledge.index"))


@bp.route("/knowledge/<int:rule_id>/delete", methods=["POST"])
def delete(rule_id):
    conn = get_db_connection(_db_path())
    conn.execute("DELETE FROM knowledge_rules WHERE id = ?", (rule_id,))
    conn.commit()
    conn.close()
    flash("Rule deleted.", "success")
    return redirect(url_for("knowledge.index"))
