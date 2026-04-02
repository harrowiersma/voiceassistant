import os
import shutil
import subprocess
from flask import Blueprint, jsonify, current_app
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
            "status": "not_configured",
            "trunk": "none",
            "active_calls": 0,
        },
        "ai": {
            "vosk": "not_loaded",
            "ollama": "not_running",
            "piper": "not_loaded",
        },
        "graph": {
            "status": "not_connected",
            "token_expires": None,
        },
    })


@bp.route("/knowledge/rules")
def knowledge_rules():
    db_path = current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")
    conn = get_db_connection(db_path)
    rules = conn.execute(
        "SELECT * FROM knowledge_rules WHERE enabled = 1 ORDER BY priority DESC, id"
    ).fetchall()
    conn.close()
    return jsonify({"rules": [dict(r) for r in rules]})
