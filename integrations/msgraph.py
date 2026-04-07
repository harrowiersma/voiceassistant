"""MS Graph client — Teams presence check and calendar free-slot finder.

Supports two auth modes:
1. App-level (client credentials) — checks any user's presence by email
   via GET /users/{email}/presence with Presence.Read.All permission.
2. Delegated (user token) — checks /me/presence for the signed-in user.

App-level is preferred when client_id + client_secret + tenant_id are configured.
"""
import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from app.helpers import get_config
from db.connection import get_db_connection

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

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

# Cache the app token (valid for ~1 hour)
_app_token_cache = {"token": None, "expires_at": None}


class MSGraphClient:
    """Wrapper around MS Graph API for presence and calendar queries."""

    def __init__(self, db_path=None):
        self.db_path = db_path

    def _get_app_token(self):
        """Get an app-level access token using client credentials flow.

        Caches the token until it expires. Returns None if credentials
        are not configured.
        """
        now = datetime.utcnow()
        if (_app_token_cache["token"] and _app_token_cache["expires_at"]
                and now < _app_token_cache["expires_at"]):
            return _app_token_cache["token"]

        client_id = get_config("graph.client_id", "", self.db_path)
        client_secret = get_config("graph.client_secret", "", self.db_path)
        tenant_id = get_config("graph.tenant_id", "", self.db_path)

        if not all([client_id, client_secret, tenant_id]):
            return None

        url = TOKEN_URL.format(tenant=tenant_id)
        data = urllib.parse.urlencode({
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        }).encode()

        req = urllib.request.Request(url, data=data, headers={
            "Content-Type": "application/x-www-form-urlencoded",
        })

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
            token = result.get("access_token")
            expires_in = result.get("expires_in", 3600)
            if token:
                _app_token_cache["token"] = token
                _app_token_cache["expires_at"] = now + timedelta(seconds=expires_in - 60)
                logger.debug("MS Graph app token acquired (expires in %ds)", expires_in)
            return token
        except Exception as e:
            logger.error("Failed to get MS Graph app token: %s", e)
            return None

    def _get_user_token(self):
        """Read a delegated user token from the DB (legacy). Returns None if absent."""
        conn = get_db_connection(self.db_path)
        row = conn.execute(
            "SELECT access_token FROM oauth_tokens WHERE provider = 'microsoft' AND person_id = 0"
        ).fetchone()
        conn.close()
        return row["access_token"] if row else None

    def _graph_get(self, endpoint, token=None):
        """Authenticated GET against MS Graph. Returns parsed JSON."""
        if token is None:
            token = self._get_app_token() or self._get_user_token()
        if token is None:
            return None
        url = f"{GRAPH_BASE}{endpoint}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())

    def check_presence(self, email=None):
        """Return simplified presence string for a user.

        If email is provided, uses app-level auth to check that user's presence.
        Otherwise falls back to /me/presence with a delegated token.

        Returns: available|busy|dnd|away|offline|unknown|not_configured
        """
        try:
            if email:
                token = self._get_app_token()
                if not token:
                    return "not_configured"
                data = self._graph_get(f"/users/{email}/presence", token=token)
            else:
                data = self._graph_get("/me/presence")
        except (TimeoutError, OSError) as e:
            logger.warning("MS Graph presence check failed: %s", e)
            return "unknown"
        except urllib.error.HTTPError as e:
            logger.warning("MS Graph presence HTTP %d for %s", e.code, email or "/me")
            return "unknown"

        if data is None:
            return "not_configured"

        availability = data.get("availability", "PresenceUnknown")
        result = PRESENCE_MAP.get(availability, "unknown")
        logger.info("MS Graph presence for %s: %s → %s", email or "/me", availability, result)
        return result

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

        busy = []
        for ev in events:
            ev_start = datetime.strptime(ev["start"]["dateTime"][:19], "%Y-%m-%dT%H:%M:%S")
            ev_end = datetime.strptime(ev["end"]["dateTime"][:19], "%Y-%m-%dT%H:%M:%S")
            ev_start = max(ev_start, start_dt)
            ev_end = min(ev_end, end_dt)
            if ev_start < ev_end:
                busy.append((ev_start, ev_end))

        busy.sort()

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

        if cursor < end_dt:
            gap_min = int((end_dt - cursor).total_seconds() / 60)
            if gap_min >= 15:
                slots.append({
                    "start": cursor.strftime("%H:%M"),
                    "end": end_dt.strftime("%H:%M"),
                    "duration_min": gap_min,
                })

        return slots
