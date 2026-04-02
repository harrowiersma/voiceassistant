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
    conn.close()
    return render_template("knowledge.html", rules=rules)


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

    conn = get_db_connection(_db_path())
    conn.execute(
        """INSERT INTO knowledge_rules
           (rule_type, trigger_keywords, response, active_from, active_until, priority)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (rule_type, trigger_keywords, response_text, active_from, active_until, priority),
    )
    conn.commit()
    conn.close()
    flash("Rule added.", "success")
    return redirect(url_for("knowledge.index"))


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
