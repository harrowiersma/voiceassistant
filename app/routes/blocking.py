from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app
from db.connection import get_db_connection

bp = Blueprint("blocking", __name__)


def _db_path():
    return current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")


@bp.route("/blocking")
def index():
    conn = get_db_connection(_db_path())
    rules = conn.execute(
        "SELECT * FROM blocked_numbers ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return render_template("blocking.html", rules=rules)


@bp.route("/blocking/add", methods=["POST"])
def add():
    pattern = request.form.get("pattern", "").strip()
    block_type = request.form.get("block_type", "exact")
    reason = request.form.get("reason", "").strip()

    if not pattern:
        flash("Pattern is required.", "error")
        return redirect(url_for("blocking.index"))

    conn = get_db_connection(_db_path())
    conn.execute(
        "INSERT INTO blocked_numbers (pattern, block_type, reason) VALUES (?, ?, ?)",
        (pattern, block_type, reason),
    )
    conn.commit()
    conn.close()

    flash(f"Blocked {block_type} pattern: {pattern}", "success")
    return redirect(url_for("blocking.index"))


@bp.route("/blocking/<int:rule_id>/delete", methods=["POST"])
def delete(rule_id):
    conn = get_db_connection(_db_path())
    conn.execute("DELETE FROM blocked_numbers WHERE id = ?", (rule_id,))
    conn.commit()
    conn.close()

    flash("Blocking rule removed.", "success")
    return redirect(url_for("blocking.index"))
