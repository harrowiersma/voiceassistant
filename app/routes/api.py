import csv
import io
import os
import shutil
import subprocess
from flask import Blueprint, jsonify, current_app, request, Response
from db.connection import get_db_connection

bp = Blueprint("api", __name__, url_prefix="/api")


def _get_cpu_temp():
    """Read Pi CPU temperature. Returns None on non-Pi systems."""
    try:
        result = subprocess.run(
            ["vcgencmd", "measure_temp"],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0:
            return float(result.stdout.strip().split("=")[1].split("'")[0])
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, IndexError):
        pass
    return None


def _check_ollama():
    """Check if Ollama API is reachable."""
    try:
        import urllib.request
        req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                return "running"
    except Exception:
        pass
    return "not_running"


def _check_asterisk():
    """Check if Asterisk PBX is running and get SIP registration status."""
    status = "not_running"
    registrations = []
    active_calls = 0
    try:
        result = subprocess.run(
            ["sudo", "asterisk", "-rx", "core show version"],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            status = "running"

        # Get SIP registrations
        reg_result = subprocess.run(
            ["sudo", "asterisk", "-rx", "pjsip show registrations"],
            capture_output=True, text=True, timeout=3
        )
        if reg_result.returncode == 0:
            for line in reg_result.stdout.splitlines():
                line = line.strip()
                if line.startswith("inbound-reg") or line.startswith("outbound-reg"):
                    name = line.split("/")[0].strip()
                    # Status is "Registered", "Unregistered", "Rejected" etc.
                    if "Registered" in line:
                        reg_status = "registered"
                    elif "Rejected" in line:
                        reg_status = "rejected"
                    else:
                        reg_status = "unregistered"
                    registrations.append({"name": name, "status": reg_status})

        # Get active calls
        chan_result = subprocess.run(
            ["sudo", "asterisk", "-rx", "core show channels count"],
            capture_output=True, text=True, timeout=3
        )
        if chan_result.returncode == 0:
            for line in chan_result.stdout.splitlines():
                if "active call" in line:
                    try:
                        active_calls = int(line.strip().split()[0])
                    except (ValueError, IndexError):
                        pass
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return status, registrations, active_calls


def _check_vosk():
    """Check if Vosk speech recognition model is loaded."""
    try:
        if os.path.exists("/opt/voice-secretary/models/vosk/model"):
            return "installed"
    except Exception:
        pass
    return "not_installed"


def _check_piper():
    """Check if Piper TTS binary is available."""
    try:
        piper_bin = "/opt/voice-secretary/.venv/bin/piper"
        if os.path.exists(piper_bin):
            return "installed"
    except Exception:
        pass
    return "not_installed"


def _get_ram_info():
    """Get RAM usage in MB."""
    try:
        with open("/proc/meminfo") as f:
            lines = f.readlines()
        meminfo = {}
        for line in lines:
            parts = line.split()
            meminfo[parts[0].rstrip(":")] = int(parts[1])
        available_kb = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
        total_kb = meminfo.get("MemTotal", 0)
        used_mb = (total_kb - available_kb) / 1024
        return round(used_mb), round(total_kb / 1024)
    except Exception:
        return 0, 0


@bp.route("/status")
def status():
    cpu_temp = _get_cpu_temp()
    ram_used, ram_total = _get_ram_info()
    disk = shutil.disk_usage("/")
    asterisk_status, registrations, active_calls = _check_asterisk()

    # Determine trunk status from registrations
    inbound_status = "not_registered"
    outbound_status = "not_registered"
    for reg in registrations:
        if "inbound" in reg["name"]:
            inbound_status = reg["status"].lower()
        if "outbound" in reg["name"]:
            outbound_status = reg["status"].lower()

    # Check MS Graph configuration status
    db_path = current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")
    graph_status = "not_configured"
    has_personas = False
    has_calls = False
    try:
        conn = get_db_connection(db_path)
        client_id = conn.execute(
            "SELECT value FROM config WHERE key = 'graph.client_id'"
        ).fetchone()
        if client_id and client_id["value"]:
            token = conn.execute(
                "SELECT * FROM oauth_tokens WHERE provider = 'msgraph' AND expires_at > datetime('now')"
            ).fetchone()
            graph_status = "connected" if token else "configured"
        has_personas = conn.execute("SELECT 1 FROM personas LIMIT 1").fetchone() is not None
        has_calls = conn.execute("SELECT 1 FROM calls LIMIT 1").fetchone() is not None
        conn.close()
    except Exception:
        pass

    return jsonify({
        "system": {
            "cpu_temp": cpu_temp,
            "ram_used_mb": ram_used,
            "ram_total_mb": ram_total,
            "ram": round(ram_used / ram_total * 100, 1) if ram_total else 0,
            "disk": round(disk.used / disk.total * 100, 1),
            "disk_used_pct": round(disk.used / disk.total * 100, 1),
        },
        "asterisk": {
            "status": asterisk_status,
            "inbound_trunk": inbound_status,
            "outbound_trunk": outbound_status,
            "active_calls": active_calls,
        },
        "ai": {
            "vosk": _check_vosk(),
            "ollama": _check_ollama(),
            "piper": _check_piper(),
        },
        "graph": {
            "status": graph_status,
        },
        "has_personas": has_personas,
        "has_calls": has_calls,
    })


@bp.route("/calls")
def calls_list():
    db_path = current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")
    conn = get_db_connection(db_path)
    action_filter = request.args.get("action")
    if action_filter:
        calls = conn.execute(
            "SELECT * FROM calls WHERE action_taken = ? ORDER BY started_at DESC LIMIT 100",
            (action_filter,),
        ).fetchall()
    else:
        calls = conn.execute(
            "SELECT * FROM calls ORDER BY started_at DESC LIMIT 100"
        ).fetchall()
    conn.close()
    return jsonify({"calls": [dict(c) for c in calls]})


@bp.route("/calls/export")
def calls_export():
    db_path = current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")
    conn = get_db_connection(db_path)
    calls = conn.execute(
        "SELECT started_at, caller_number, caller_name, duration_seconds, reason, action_taken "
        "FROM calls ORDER BY started_at DESC"
    ).fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["started_at", "caller_number", "caller_name", "duration_seconds", "reason", "action_taken"])
    for call in calls:
        writer.writerow([call["started_at"], call["caller_number"], call["caller_name"],
                         call["duration_seconds"], call["reason"], call["action_taken"]])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=calls.csv"},
    )


@bp.route("/blocking/check")
def blocking_check():
    number = request.args.get("number", "")
    db_path = current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")
    conn = get_db_connection(db_path)
    rules = conn.execute("SELECT * FROM blocked_numbers").fetchall()
    conn.close()
    for rule in rules:
        if rule["block_type"] == "exact" and rule["pattern"] == number:
            return jsonify({"blocked": True, "reason": rule["reason"]})
        elif rule["block_type"] == "prefix" and number.startswith(rule["pattern"]):
            return jsonify({"blocked": True, "reason": rule["reason"]})
    return jsonify({"blocked": False})


@bp.route("/personas")
def personas_list():
    db_path = current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")
    conn = get_db_connection(db_path)
    personas = conn.execute("SELECT * FROM personas WHERE enabled = 1 ORDER BY is_default DESC, name").fetchall()
    conn.close()
    return jsonify({"personas": [dict(p) for p in personas]})


@bp.route("/knowledge/rules")
def knowledge_rules():
    db_path = current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")
    conn = get_db_connection(db_path)
    persona_id = request.args.get("persona_id")
    if persona_id:
        rules = conn.execute(
            "SELECT * FROM knowledge_rules WHERE enabled = 1 AND (persona_id = ? OR persona_id IS NULL) ORDER BY priority DESC, id",
            (int(persona_id),),
        ).fetchall()
    else:
        rules = conn.execute(
            "SELECT * FROM knowledge_rules WHERE enabled = 1 ORDER BY priority DESC, id"
        ).fetchall()
    conn.close()
    return jsonify({"rules": [dict(r) for r in rules]})
