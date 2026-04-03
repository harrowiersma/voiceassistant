import json

from flask import Blueprint, render_template, current_app
from db.connection import get_db_connection

bp = Blueprint("calls", __name__)


def _db_path():
    return current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")


@bp.route("/calls")
def index():
    conn = get_db_connection(_db_path())
    calls = conn.execute(
        "SELECT * FROM calls ORDER BY started_at DESC LIMIT 100"
    ).fetchall()
    conn.close()

    result = []
    for c in calls:
        row = dict(c)
        # Parse transcript JSON for template rendering
        if row.get("transcript"):
            try:
                row["_transcript_parsed"] = json.loads(row["transcript"])
            except (json.JSONDecodeError, TypeError):
                row["_transcript_parsed"] = None
        else:
            row["_transcript_parsed"] = None
        result.append(row)

    return render_template("calls.html", calls=result)
