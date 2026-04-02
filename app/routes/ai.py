from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app
from app.helpers import get_config, set_config
from config.defaults import AI_DEFAULTS

bp = Blueprint("ai", __name__)

AI_FIELDS = [
    "ai.stt_model",
    "ai.llm_model",
    "ai.tts_voice",
    "ai.response_timeout",
    "ai.max_call_duration",
]


def _db_path():
    return current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")


@bp.route("/ai")
def index():
    db = _db_path()
    values = {}
    for key in AI_FIELDS:
        values[key] = get_config(key, default=AI_DEFAULTS.get(key, ""), db_path=db)
    return render_template("ai.html", values=values)


@bp.route("/ai/save", methods=["POST"])
def save():
    db = _db_path()
    for key in AI_FIELDS:
        value = request.form.get(key, "")
        set_config(key, value, "ai", db_path=db)
    flash("AI settings saved.", "success")
    return redirect(url_for("ai.index"))
