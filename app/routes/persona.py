from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app
from app.helpers import get_config, set_config
from config.defaults import PERSONA_DEFAULTS

bp = Blueprint("persona", __name__)

PERSONA_FIELDS = [
    "persona.company_name",
    "persona.greeting",
    "persona.personality",
    "persona.unavailable_message",
]


def _db_path():
    return current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")


@bp.route("/persona")
def index():
    db = _db_path()
    values = {}
    for key in PERSONA_FIELDS:
        values[key] = get_config(key, default=PERSONA_DEFAULTS.get(key, ""), db_path=db)
    return render_template("persona.html", values=values)


@bp.route("/persona/save", methods=["POST"])
def save():
    db = _db_path()
    for key in PERSONA_FIELDS:
        value = request.form.get(key, "")
        set_config(key, value, "persona", db_path=db)
    flash("Persona settings saved.", "success")
    return redirect(url_for("persona.index"))
