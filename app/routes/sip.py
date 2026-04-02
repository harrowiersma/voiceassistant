from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app
from app.helpers import get_config, set_config
from config.defaults import SIP_DEFAULTS

bp = Blueprint("sip", __name__)

SIP_FIELDS = [
    "sip.inbound_server",
    "sip.inbound_username",
    "sip.inbound_password",
    "sip.inbound_port",
    "sip.outbound_server",
    "sip.outbound_username",
    "sip.outbound_password",
    "sip.outbound_port",
    "sip.forward_number",
]


def _db_path():
    return current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")


@bp.route("/sip")
def index():
    db = _db_path()
    values = {}
    for key in SIP_FIELDS:
        values[key] = get_config(key, default=SIP_DEFAULTS.get(key, ""), db_path=db)
    return render_template("sip.html", values=values)


@bp.route("/sip/save", methods=["POST"])
def save():
    db = _db_path()
    for key in SIP_FIELDS:
        value = request.form.get(key, "")
        set_config(key, value, "sip", db_path=db)
    flash("SIP settings saved.", "success")
    return redirect(url_for("sip.index"))
