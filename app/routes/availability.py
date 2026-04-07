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

    # Check Google Calendar connection status
    from db.connection import get_db_connection
    conn = get_db_connection(db)
    google_token = conn.execute(
        "SELECT access_token, expires_at FROM oauth_tokens WHERE provider = 'google'"
    ).fetchone()
    conn.close()
    google_connected = google_token is not None and google_token["access_token"]

    return render_template("availability.html", values=values, google_connected=google_connected)


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
