import os
import subprocess

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
    "sip.stun_server",
    "sip.extension_1_name",
    "sip.extension_1_password",
    "sip.extension_2_name",
    "sip.extension_2_password",
    "sip.extension_3_name",
    "sip.extension_3_password",
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

    # Auto-apply: regenerate Asterisk config and reload
    config_dir = current_app.config.get("ASTERISK_CONFIG_DIR", "/etc/asterisk")
    config = {}
    for key in SIP_FIELDS:
        config[key] = get_config(key, default=SIP_DEFAULTS.get(key, ""), db_path=db)

    from config.asterisk_gen import render_pjsip_conf, render_extensions_conf, render_rtp_conf

    try:
        os.makedirs(config_dir, exist_ok=True)
        with open(os.path.join(config_dir, "pjsip.conf"), "w") as f:
            f.write(render_pjsip_conf(config))
        with open(os.path.join(config_dir, "extensions.conf"), "w") as f:
            f.write(render_extensions_conf(config))
        with open(os.path.join(config_dir, "rtp.conf"), "w") as f:
            f.write(render_rtp_conf(config))
        try:
            subprocess.run(
                ["asterisk", "-rx", "core reload"],
                capture_output=True,
                timeout=5,
            )
            flash("Settings saved and applied to Asterisk.", "success")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            flash("Settings saved. Asterisk will reload on the Pi.", "success")
    except Exception as e:
        flash(f"Settings saved but failed to apply: {e}", "error")

    return redirect(url_for("sip.index"))


@bp.route("/sip/apply", methods=["POST"])
def apply_config():
    """Legacy route — redirects to save which now auto-applies."""
    return redirect(url_for("sip.save"), code=307)
