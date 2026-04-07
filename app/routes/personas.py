from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from db.connection import get_db_connection

bp = Blueprint("personas", __name__)

# Map country calling codes to timezones
COUNTRY_CODE_TZ = {
    "1": "America/New_York", "31": "Europe/Amsterdam", "32": "Europe/Brussels",
    "33": "Europe/Paris", "34": "Europe/Madrid", "39": "Europe/Rome",
    "41": "Europe/Zurich", "43": "Europe/Vienna", "44": "Europe/London",
    "49": "Europe/Berlin", "351": "Europe/Lisbon", "352": "Europe/Luxembourg",
    "353": "Europe/Dublin", "354": "Atlantic/Reykjavik", "356": "Europe/Malta",
    "358": "Europe/Helsinki", "359": "Europe/Sofia", "370": "Europe/Vilnius",
    "371": "Europe/Riga", "372": "Europe/Tallinn", "380": "Europe/Kyiv",
    "385": "Europe/Zagreb", "386": "Europe/Ljubljana", "420": "Europe/Prague",
    "421": "Europe/Bratislava", "48": "Europe/Warsaw", "45": "Europe/Copenhagen",
    "46": "Europe/Stockholm", "47": "Europe/Oslo", "30": "Europe/Athens",
    "36": "Europe/Budapest", "40": "Europe/Bucharest",
    "61": "Australia/Sydney", "81": "Asia/Tokyo", "86": "Asia/Shanghai",
    "91": "Asia/Kolkata", "971": "Asia/Dubai", "972": "Asia/Jerusalem",
}


def _guess_timezone(number):
    """Guess timezone from phone number country code."""
    if not number:
        return ""
    num = number.lstrip("+").lstrip("0")
    for length in (3, 2, 1):
        code = num[:length]
        if code in COUNTRY_CODE_TZ:
            return COUNTRY_CODE_TZ[code]
    return ""


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
    inbound = request.form.get("inbound_number", "")
    tz = request.form.get("timezone", "").strip()
    if not tz:
        tz = _guess_timezone(inbound)
    conn = get_db_connection(_db_path())
    conn.execute(
        "INSERT INTO personas (name, company_name, greeting, personality, unavailable_message, calendar_type, inbound_number, timezone) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (request.form["name"], request.form.get("company_name", ""),
         request.form.get("greeting", ""), request.form.get("personality", ""),
         request.form.get("unavailable_message", ""), request.form.get("calendar_type", "none"),
         inbound, tz),
    )
    conn.commit()
    conn.close()
    flash("Persona created.", "success")
    return redirect(url_for("personas.index"))


@bp.route("/personas/<int:persona_id>/edit", methods=["GET", "POST"])
def edit(persona_id):
    conn = get_db_connection(_db_path())
    if request.method == "POST":
        inbound = request.form.get("inbound_number", "")
        tz = request.form.get("timezone", "").strip()
        if not tz:
            tz = _guess_timezone(inbound)
        conn.execute(
            "UPDATE personas SET name=?, company_name=?, greeting=?, personality=?, "
            "unavailable_message=?, calendar_type=?, inbound_number=?, timezone=? WHERE id=?",
            (request.form["name"], request.form.get("company_name", ""),
             request.form.get("greeting", ""), request.form.get("personality", ""),
             request.form.get("unavailable_message", ""), request.form.get("calendar_type", "none"),
             inbound, tz, persona_id),
        )
        conn.commit()
        conn.close()
        flash("Persona updated.", "success")
        return redirect(url_for("personas.index"))
    persona = conn.execute("SELECT * FROM personas WHERE id = ?", (persona_id,)).fetchone()
    conn.close()
    return render_template("persona_edit.html", persona=dict(persona))


@bp.route("/personas/<int:persona_id>/duplicate", methods=["POST"])
def duplicate(persona_id):
    conn = get_db_connection(_db_path())
    original = conn.execute("SELECT * FROM personas WHERE id = ?", (persona_id,)).fetchone()
    if not original:
        flash("Persona not found.", "error")
        conn.close()
        return redirect(url_for("personas.index"))
    conn.execute(
        "INSERT INTO personas (name, company_name, greeting, personality, unavailable_message, "
        "calendar_type, inbound_number, timezone, is_default, enabled) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 1)",
        (f"{original['name']} (copy)", original["company_name"], original["greeting"],
         original["personality"], original["unavailable_message"], original["calendar_type"],
         "", original["timezone"]),
    )
    new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    flash(f"Persona duplicated. Edit the copy to customize it.", "success")
    return redirect(url_for("personas.edit", persona_id=new_id))


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
