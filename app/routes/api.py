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
            # Output: temp=52.0'C
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
    """Check if Asterisk PBX is running."""
    try:
        result = subprocess.run(
            ["asterisk", "-rx", "core show version"],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            return "running"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return "not_running"


def _check_vosk():
    """Check if Vosk speech recognition library is installed."""
    try:
        import vosk  # noqa: F401
        return "installed"
    except ImportError:
        return "not_installed"


def _check_piper():
    """Check if Piper TTS binary is available."""
    try:
        result = subprocess.run(["piper", "--version"], capture_output=True, timeout=2)
        return "installed" if result.returncode == 0 else "not_installed"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "not_installed"


def _get_ram_info():
    """Get RAM usage in MB."""
    try:
        # Cross-platform fallback
        mem = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        total_mb = mem / (1024 * 1024)
        # Approximate used from /proc/meminfo on Linux
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
        except FileNotFoundError:
            return 0, round(total_mb)
    except Exception:
        return 0, 0


@bp.route("/status")
def status():
    cpu_temp = _get_cpu_temp()
    ram_used, ram_total = _get_ram_info()
    disk = shutil.disk_usage("/")

    return jsonify({
        "system": {
            "cpu_temp": cpu_temp,
            "ram_used_mb": ram_used,
            "ram_total_mb": ram_total,
            "disk_used_pct": round(disk.used / disk.total * 100, 1),
        },
        "asterisk": {
            "status": _check_asterisk(),
            "trunk": "none",
            "active_calls": 0,
        },
        "ai": {
            "vosk": _check_vosk(),
            "ollama": _check_ollama(),
            "piper": _check_piper(),
        },
        "graph": {
            "status": "not_connected",
            "token_expires": None,
        },
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


@bp.route("/knowledge/rules")
def knowledge_rules():
    db_path = current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")
    conn = get_db_connection(db_path)
    rules = conn.execute(
        "SELECT * FROM knowledge_rules WHERE enabled = 1 ORDER BY priority DESC, id"
    ).fetchall()
    conn.close()
    return jsonify({"rules": [dict(r) for r in rules]})
