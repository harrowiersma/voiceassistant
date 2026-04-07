import glob
import json
import logging
import os

from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app
from app.helpers import get_config, set_config
from config.defaults import AI_DEFAULTS

bp = Blueprint("ai", __name__)
logger = logging.getLogger(__name__)

AI_FIELDS = [
    "ai.stt_model",
    "ai.llm_model",
    "ai.tts_voice",
    "ai.response_timeout",
    "ai.max_call_duration",
]

PIPER_MODEL_DIR = "/opt/voice-secretary/models/piper"


def _db_path():
    return current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")


def _get_ollama_models():
    """Fetch installed Ollama models."""
    try:
        import urllib.request
        req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def _get_piper_voices():
    """List installed Piper voice models."""
    try:
        voices = []
        for path in glob.glob(os.path.join(PIPER_MODEL_DIR, "*.onnx")):
            name = os.path.basename(path).replace(".onnx", "")
            voices.append(name)
        return sorted(voices)
    except Exception:
        return []


@bp.route("/ai")
def index():
    db = _db_path()
    values = {}
    for key in AI_FIELDS:
        values[key] = get_config(key, default=AI_DEFAULTS.get(key, ""), db_path=db)

    ollama_models = _get_ollama_models()
    piper_voices = _get_piper_voices()

    return render_template("ai.html", values=values,
                           ollama_models=ollama_models, piper_voices=piper_voices)


@bp.route("/ai/save", methods=["POST"])
def save():
    db = _db_path()
    for key in AI_FIELDS:
        value = request.form.get(key, "")
        set_config(key, value, "ai", db_path=db)
    flash("AI settings saved.", "success")
    return redirect(url_for("ai.index"))
