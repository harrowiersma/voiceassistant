from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app
from app.helpers import get_config, set_config
from config.defaults import ACTIONS_DEFAULTS

bp = Blueprint("actions", __name__)

ACTIONS_FIELDS = [
    "actions.smtp_server", "actions.smtp_port", "actions.smtp_username",
    "actions.smtp_password", "actions.email_to", "actions.email_from",
    "actions.notify_on",
]


def _db_path():
    return current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")


@bp.route("/actions")
def index():
    db = _db_path()
    values = {}
    for key in ACTIONS_FIELDS:
        values[key] = get_config(key, default=ACTIONS_DEFAULTS.get(key, ""), db_path=db)
    return render_template("actions.html", values=values)


@bp.route("/actions/save", methods=["POST"])
def save():
    db = _db_path()
    for key in ACTIONS_FIELDS:
        value = request.form.get(key, "")
        set_config(key, value, "actions", db_path=db)
    flash("Actions settings saved.", "success")
    return redirect(url_for("actions.index"))
