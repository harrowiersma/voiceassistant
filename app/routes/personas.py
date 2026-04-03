from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from db.connection import get_db_connection

bp = Blueprint("personas", __name__)


def _db_path():
    return current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")


@bp.route("/personas")
def index():
    conn = get_db_connection(_db_path())
    personas = conn.execute("SELECT * FROM personas ORDER BY is_default DESC, name").fetchall()
    conn.close()
    return render_template("personas.html", personas=[dict(p) for p in personas])


@bp.route("/personas/add", methods=["POST"])
def add():
    conn = get_db_connection(_db_path())
    conn.execute(
        "INSERT INTO personas (name, company_name, greeting, personality, unavailable_message, calendar_type, inbound_number) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (request.form["name"], request.form.get("company_name", ""),
         request.form.get("greeting", ""), request.form.get("personality", ""),
         request.form.get("unavailable_message", ""), request.form.get("calendar_type", "none"),
         request.form.get("inbound_number", "")),
    )
    conn.commit()
    conn.close()
    flash("Persona created.", "success")
    return redirect(url_for("personas.index"))


@bp.route("/personas/<int:persona_id>/edit", methods=["GET", "POST"])
def edit(persona_id):
    conn = get_db_connection(_db_path())
    if request.method == "POST":
        conn.execute(
            "UPDATE personas SET name=?, company_name=?, greeting=?, personality=?, "
            "unavailable_message=?, calendar_type=?, inbound_number=? WHERE id=?",
            (request.form["name"], request.form.get("company_name", ""),
             request.form.get("greeting", ""), request.form.get("personality", ""),
             request.form.get("unavailable_message", ""), request.form.get("calendar_type", "none"),
             request.form.get("inbound_number", ""), persona_id),
        )
        conn.commit()
        conn.close()
        flash("Persona updated.", "success")
        return redirect(url_for("personas.index"))
    persona = conn.execute("SELECT * FROM personas WHERE id = ?", (persona_id,)).fetchone()
    conn.close()
    return render_template("persona_edit.html", persona=dict(persona))


@bp.route("/personas/<int:persona_id>/delete", methods=["POST"])
def delete(persona_id):
    conn = get_db_connection(_db_path())
    persona = conn.execute("SELECT * FROM personas WHERE id = ?", (persona_id,)).fetchone()
    if persona and persona["is_default"]:
        flash("Cannot delete the default persona.", "error")
    else:
        conn.execute("DELETE FROM personas WHERE id = ?", (persona_id,))
        conn.commit()
        flash("Persona deleted.", "success")
    conn.close()
    return redirect(url_for("personas.index"))
