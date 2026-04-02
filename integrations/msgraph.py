"""MS Graph client — Teams presence check and calendar free-slot finder."""
import json
import urllib.request
from datetime import datetime, timedelta

from db.connection import get_db_connection

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

PRESENCE_MAP = {
    "Available": "available",
    "AvailableIdle": "available",
    "Busy": "busy",
    "BusyIdle": "busy",
    "DoNotDisturb": "dnd",
    "BeRightBack": "away",
    "Away": "away",
    "Offline": "offline",
    "PresenceUnknown": "unknown",
}


class MSGraphClient:
    """Thin wrapper around MS Graph API for presence and calendar queries."""

    def __init__(self, db_path=None):
        self.db_path = db_path

    # ── internal helpers ────────────────────────────────────────

    def _get_token(self):
        """Read the Microsoft access token from the DB. Returns None if absent."""
        conn = get_db_connection(self.db_path)
        row = conn.execute(
            "SELECT access_token FROM oauth_tokens WHERE provider = 'microsoft'"
        ).fetchone()
        conn.close()
        return row["access_token"] if row else None

    def _graph_get(self, endpoint):
        """Authenticated GET against MS Graph. Returns parsed JSON."""
        token = self._get_token()
        if token is None:
            return None
        url = f"{GRAPH_BASE}{endpoint}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())

    # ── public API ──────────────────────────────────────────────

    def check_presence(self):
        """Return simplified presence string: available|busy|dnd|away|offline|unknown|not_configured."""
        try:
            data = self._graph_get("/me/presence")
        except (TimeoutError, OSError):
            return "unknown"

        if data is None:
            return "not_configured"

        availability = data.get("availability", "PresenceUnknown")
        return PRESENCE_MAP.get(availability, "unknown")

    def get_free_slots(self, date, business_start=9, business_end=17):
        """Find free slots between events on *date* (YYYY-MM-DD string).

        Returns a list of dicts: {"start": "HH:MM", "end": "HH:MM", "duration_min": int}.
        Minimum slot duration is 15 minutes.
        """
        start_dt = datetime.strptime(date, "%Y-%m-%d").replace(hour=business_start)
        end_dt = datetime.strptime(date, "%Y-%m-%d").replace(hour=business_end)

        start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%S")
        end_iso = end_dt.strftime("%Y-%m-%dT%H:%M:%S")

        endpoint = (
            f"/me/calendarView?startDateTime={start_iso}&endDateTime={end_iso}"
            "&$orderby=start/dateTime&$select=start,end"
        )

        try:
            data = self._graph_get(endpoint)
        except (TimeoutError, OSError):
            return []

        if data is None:
            return []

        events = data.get("value", [])

        # Build sorted list of busy intervals (clamped to business hours)
        busy = []
        for ev in events:
            ev_start = datetime.strptime(ev["start"]["dateTime"][:19], "%Y-%m-%dT%H:%M:%S")
            ev_end = datetime.strptime(ev["end"]["dateTime"][:19], "%Y-%m-%dT%H:%M:%S")
            ev_start = max(ev_start, start_dt)
            ev_end = min(ev_end, end_dt)
            if ev_start < ev_end:
                busy.append((ev_start, ev_end))

        busy.sort()

        # Walk through business hours, collecting gaps
        slots = []
        cursor = start_dt
        for b_start, b_end in busy:
            if cursor < b_start:
                gap_min = int((b_start - cursor).total_seconds() / 60)
                if gap_min >= 15:
                    slots.append({
                        "start": cursor.strftime("%H:%M"),
                        "end": b_start.strftime("%H:%M"),
                        "duration_min": gap_min,
                    })
            cursor = max(cursor, b_end)

        # Trailing gap after last event
        if cursor < end_dt:
            gap_min = int((end_dt - cursor).total_seconds() / 60)
            if gap_min >= 15:
                slots.append({
                    "start": cursor.strftime("%H:%M"),
                    "end": end_dt.strftime("%H:%M"),
                    "duration_min": gap_min,
                })

        return slots
