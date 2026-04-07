from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app
from app.helpers import get_config, set_config
from config.defaults import AVAILABILITY_DEFAULTS

bp = Blueprint("availability", __name__)

AVAILABILITY_FIELDS = [
    "availability.manual_override",
    "availability.business_hours_start",
    "availability.business_hours_end",
    "availability.action_available",
    "availability.action_busy",
    "availability.action_dnd",
    "availability.action_away",
    "security.code_word",
    "graph.client_id",
    "graph.client_secret",
    "graph.tenant_id",
    "google.client_id",
    "google.client_secret",
]


def _db_path():
    return current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")


@bp.route("/availability")
def index():
    db = _db_path()
    values = {}
    for key in AVAILABILITY_FIELDS:
        values[key] = get_config(key, default=AVAILABILITY_DEFAULTS.get(key, ""), db_path=db)

    from db.connection import get_db_connection
    conn = get_db_connection(db)

    # Check Google Calendar: global fallback token (person_id=0)
    google_global = conn.execute(
        "SELECT 1 FROM oauth_tokens WHERE provider = 'google' AND person_id = 0 AND access_token IS NOT NULL"
    ).fetchone()

    # Check per-person Google tokens
    google_persons = conn.execute(
        "SELECT p.name, ot.person_id FROM oauth_tokens ot "
        "JOIN persons p ON ot.person_id = p.id "
        "WHERE ot.provider = 'google' AND ot.person_id > 0"
    ).fetchall()

    # Check MS Graph: app credentials configured?
    graph_configured = bool(values.get("graph.client_id") and values.get("graph.client_secret") and values.get("graph.tenant_id"))

    conn.close()

    return render_template("availability.html", values=values,
                           google_global=google_global is not None,
                           google_persons=[dict(p) for p in google_persons],
                           graph_configured=graph_configured)


@bp.route("/availability/save", methods=["POST"])
def save():
    db = _db_path()
    for key in AVAILABILITY_FIELDS:
        value = request.form.get(key, "")
        if key.startswith("graph."):
            category = "graph"
        elif key.startswith("google."):
            category = "google"
        elif key.startswith("security."):
            category = "security"
        else:
            category = "availability"
        set_config(key, value, category, db_path=db)
    flash("Availability settings saved.", "success")
    return redirect(url_for("availability.index"))
