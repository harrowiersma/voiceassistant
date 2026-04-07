"""Persons (employees/team members) — each has their own calendar & forward number."""

from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app
from db.connection import get_db_connection

bp = Blueprint("persons", __name__)


def _db_path():
    return current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")


@bp.route("/persons")
def index():
    db = _db_path()
    conn = get_db_connection(db)
    persons = conn.execute(
        "SELECT p.*, per.name as persona_name, per.company_name "
        "FROM persons p LEFT JOIN personas per ON p.persona_id = per.id "
        "ORDER BY per.name, p.name"
    ).fetchall()
    personas = conn.execute("SELECT id, name, company_name FROM personas WHERE enabled = 1 ORDER BY name").fetchall()
    conn.close()
    return render_template("persons.html", persons=persons, personas=personas)


@bp.route("/persons/add", methods=["POST"])
def add():
    db = _db_path()
    conn = get_db_connection(db)
    # calendar_types comes as a list of checkboxes (multi-select)
    cal_types = request.form.getlist("calendar_types")
    calendar_type = ",".join(cal_types) if cal_types else "none"
    conn.execute(
        "INSERT INTO persons (name, aliases, persona_id, forward_number, internal_extension, calendar_type, email, is_owner) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            request.form["name"],
            request.form.get("aliases", ""),
            int(request.form["persona_id"]),
            request.form.get("forward_number", ""),
            request.form.get("internal_extension", ""),
            calendar_type,
            request.form.get("email", ""),
            bool(request.form.get("is_owner")),
        ),
    )
    conn.commit()
    conn.close()
    flash(f"Person '{request.form['name']}' added.", "success")
    return redirect(url_for("persons.index"))


@bp.route("/persons/<int:person_id>/edit", methods=["GET", "POST"])
def edit(person_id):
    db = _db_path()
    conn = get_db_connection(db)

    if request.method == "POST":
        cal_types = request.form.getlist("calendar_types")
        calendar_type = ",".join(cal_types) if cal_types else "none"
        conn.execute(
            "UPDATE persons SET name=?, aliases=?, persona_id=?, forward_number=?, "
            "internal_extension=?, calendar_type=?, email=?, is_owner=? WHERE id=?",
            (
                request.form["name"],
                request.form.get("aliases", ""),
                int(request.form["persona_id"]),
                request.form.get("forward_number", ""),
                request.form.get("internal_extension", ""),
                calendar_type,
                request.form.get("email", ""),
                bool(request.form.get("is_owner")),
                person_id,
            ),
        )
        conn.commit()
        conn.close()
        flash("Person updated.", "success")
        return redirect(url_for("persons.index"))

    person = conn.execute("SELECT * FROM persons WHERE id = ?", (person_id,)).fetchone()
    personas = conn.execute("SELECT id, name, company_name FROM personas WHERE enabled = 1 ORDER BY name").fetchall()
    # Check if this person has a Google Calendar token
    google_token = conn.execute(
        "SELECT 1 FROM oauth_tokens WHERE provider = 'google' AND person_id = ?",
        (person_id,),
    ).fetchone()
    conn.close()
    if not person:
        flash("Person not found.", "error")
        return redirect(url_for("persons.index"))
    return render_template("person_edit.html", person=dict(person), personas=personas,
                           google_connected=google_token is not None)


@bp.route("/persons/<int:person_id>/delete", methods=["POST"])
def delete(person_id):
    db = _db_path()
    conn = get_db_connection(db)
    conn.execute("DELETE FROM persons WHERE id = ?", (person_id,))
    conn.commit()
    conn.close()
    flash("Person deleted.", "success")
    return redirect(url_for("persons.index"))
