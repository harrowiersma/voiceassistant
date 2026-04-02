import subprocess
from flask import Blueprint, render_template

bp = Blueprint("system_mgmt", __name__)

SERVICES = [
    {"name": "Asterisk PBX", "service": "asterisk"},
    {"name": "Ollama LLM", "service": "ollama"},
    {"name": "Voice Secretary Engine", "service": "voice-secretary-engine"},
    {"name": "Voice Secretary Web", "service": "voice-secretary-web"},
]

def _service_status(service_name):
    try:
        result = subprocess.run(
            ["systemctl", "is-active", service_name],
            capture_output=True, text=True, timeout=3
        )
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "unknown"

@bp.route("/system")
def index():
    services = []
    for svc in SERVICES:
        status = _service_status(svc["service"])
        services.append({**svc, "status": status})
    return render_template("system.html", services=services)
