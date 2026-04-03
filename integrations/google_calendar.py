"""Google Calendar client — free-slot finder and busy check."""
import json
import urllib.request
from datetime import datetime, timedelta, timezone

GCAL_BASE = "https://www.googleapis.com/calendar/v3"


class GoogleCalendarClient:
    """Thin wrapper around Google Calendar API v3 for free slots and busy check."""

    def __init__(self, access_token=None):
        self.access_token = access_token

    # ── internal helpers ────────────────────────────────────────

    def _gcal_get(self, endpoint):
        """Authenticated GET against Google Calendar API. Returns parsed JSON."""
        if self.access_token is None:
            return None
        url = f"{GCAL_BASE}{endpoint}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())

    def _gcal_post(self, endpoint, data):
        """Authenticated POST against Google Calendar API. Returns parsed JSON."""
        if self.access_token is None:
            return None
        url = f"{GCAL_BASE}{endpoint}"
        body = json.dumps(data).encode()
        req = urllib.request.Request(url, data=body, headers={
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())

    # ── public API ──────────────────────────────────────────────

    def get_free_slots(self, date=None, business_start=9, business_end=17):
        """Find free slots between events on *date* (YYYY-MM-DD string).

        Returns a list of dicts: {"start": "HH:MM", "end": "HH:MM", "duration_min": int}.
        Minimum slot duration is 15 minutes.
        """
        if self.access_token is None:
            return []

        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

        start_dt = datetime.strptime(date, "%Y-%m-%d").replace(hour=business_start)
        end_dt = datetime.strptime(date, "%Y-%m-%d").replace(hour=business_end)

        start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
        end_iso = end_dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"

        endpoint = (
            f"/calendars/primary/events"
            f"?timeMin={start_iso}&timeMax={end_iso}"
            f"&singleEvents=true&orderBy=startTime"
            f"&fields=items(start,end)"
        )

        try:
            data = self._gcal_get(endpoint)
        except (TimeoutError, OSError):
            return []

        if data is None:
            return []

        events = data.get("items", [])

        # Build sorted list of busy intervals (clamped to business hours)
        busy = []
        for ev in events:
            ev_start_str = ev.get("start", {}).get("dateTime", "")
            ev_end_str = ev.get("end", {}).get("dateTime", "")
            if not ev_start_str or not ev_end_str:
                continue
            # Parse ISO 8601 with timezone, then strip tz for local comparison
            ev_start = datetime.fromisoformat(ev_start_str).replace(tzinfo=None)
            ev_end = datetime.fromisoformat(ev_end_str).replace(tzinfo=None)
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

    def is_busy_now(self):
        """Check if the user is busy right now using the freeBusy API. Returns bool."""
        if self.access_token is None:
            return False

        now = datetime.now(timezone.utc)
        time_min = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        time_max = (now + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

        query = {
            "timeMin": time_min,
            "timeMax": time_max,
            "items": [{"id": "primary"}],
        }

        try:
            data = self._gcal_post("/freeBusy", query)
        except (TimeoutError, OSError):
            return False

        if data is None:
            return False

        busy_list = (
            data.get("calendars", {})
            .get("primary", {})
            .get("busy", [])
        )
        return len(busy_list) > 0
