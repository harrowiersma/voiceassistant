"""LLM tool definitions and dispatcher for the voice secretary."""
from datetime import datetime

# ── Tool definitions (Ollama tool-calling format) ──────────────────────

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "check_availability",
            "description": (
                "Check whether the person being called is currently available "
                "by looking at their Teams presence status."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forward_call",
            "description": "Transfer the current call to the configured forward number.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "take_message",
            "description": (
                "Record a message from the caller including their name, reason "
                "for calling, and whether they would like a callback."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "caller_name": {
                        "type": "string",
                        "description": "Name of the caller.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for the call or message content.",
                    },
                    "callback_requested": {
                        "type": "boolean",
                        "description": "Whether the caller wants a callback.",
                    },
                },
                "required": ["caller_name", "reason", "callback_requested"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_callback_times",
            "description": (
                "Look up free calendar slots and suggest times the caller "
                "could receive a callback."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": (
                            "Date to check in YYYY-MM-DD format. "
                            "Defaults to today if omitted."
                        ),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "end_call",
            "description": "End the current phone call.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": (
                            "Why the call is ending, e.g. caller_goodbye, "
                            "message_taken, forwarded, timeout."
                        ),
                    },
                },
                "required": ["reason"],
            },
        },
    },
]

# ── Action map: presence -> recommended action ─────────────────────────

def _get_google_token(db_path=None):
    """Get a valid Google access token, refreshing if expired."""
    from db.connection import get_db_connection
    conn = get_db_connection(db_path)
    row = conn.execute(
        "SELECT access_token, refresh_token, expires_at FROM oauth_tokens WHERE provider = 'google'"
    ).fetchone()
    conn.close()
    if not row:
        return None

    # Check if token is expired
    expires_at = row["expires_at"]
    if expires_at:
        from datetime import datetime
        try:
            exp = datetime.fromisoformat(expires_at)
            if datetime.utcnow() >= exp:
                from app.routes.google_oauth import refresh_google_token
                new_token = refresh_google_token(db_path)
                return new_token
        except (ValueError, TypeError):
            pass

    return row["access_token"]


_PRESENCE_ACTION = {
    "available": "forward",
    "busy": "take_message",
    "dnd": "take_message",
    "away": "take_message",
    "offline": "take_message",
    "unknown": "take_message",
    "not_configured": "take_message",
}

# ── Handler functions ──────────────────────────────────────────────────


def _handle_check_availability(arguments, db_path=None, mock_presence=None,
                               person=None):
    """Check availability across all configured calendar sources for a person.

    Merges results: if ANY source says busy/dnd, the person is unavailable.
    Supports per-person multi-calendar (calendar_type='msgraph,google').
    """
    if mock_presence is not None:
        return {
            "status": mock_presence,
            "action": _PRESENCE_ACTION.get(mock_presence, "take_message"),
        }

    # Determine which calendar sources to check
    cal_types = []
    if person and person.get("calendar_type"):
        cal_types = [c.strip() for c in person["calendar_type"].split(",") if c.strip() and c.strip() != "none"]

    # Fall back to MS Graph only (legacy behaviour when no person context)
    if not cal_types:
        cal_types = ["msgraph"]

    statuses = []

    for cal in cal_types:
        if cal == "msgraph":
            from integrations.msgraph import MSGraphClient
            client = MSGraphClient(db_path=db_path)
            statuses.append(client.check_presence())
        elif cal == "google":
            from integrations.google_calendar import GoogleCalendarClient
            token = _get_google_token(db_path)
            if token:
                gcal = GoogleCalendarClient(access_token=token)
                is_busy = gcal.is_busy_now()
                statuses.append("busy" if is_busy else "available")
            else:
                statuses.append("not_configured")

    # Merge: worst status wins (busy > dnd > away > available)
    priority = ["busy", "dnd", "away", "offline", "unknown", "not_configured", "available"]
    merged = "available"
    for s in statuses:
        if priority.index(s) < priority.index(merged) if s in priority else False:
            merged = s

    return {
        "status": merged,
        "action": _PRESENCE_ACTION.get(merged, "take_message"),
        "sources": dict(zip(cal_types, statuses)),
    }


def _handle_forward_call(arguments, db_path=None, **_kw):
    """Return the configured forward number so Asterisk can transfer."""
    from app.helpers import get_config
    number = get_config("sip.forward_number", default=None, db_path=db_path)
    if number is None:
        return {"action": "forward", "number": None, "error": "forward_number not configured"}
    return {"action": "forward", "number": number}


def _handle_take_message(arguments, db_path=None, **_kw):
    """Acknowledge a recorded message with caller details."""
    return {
        "success": True,
        "caller_name": arguments.get("caller_name", "Unknown"),
        "reason": arguments.get("reason", ""),
        "callback_requested": arguments.get("callback_requested", False),
        "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }


def _handle_suggest_callback_times(arguments, db_path=None, person=None, **_kw):
    """Query configured calendars for free slots, intersecting across sources."""
    date = arguments.get("date") or datetime.utcnow().strftime("%Y-%m-%d")

    cal_types = []
    if person and person.get("calendar_type"):
        cal_types = [c.strip() for c in person["calendar_type"].split(",") if c.strip() and c.strip() != "none"]
    if not cal_types:
        cal_types = ["msgraph"]

    all_slots = []
    for cal in cal_types:
        if cal == "msgraph":
            from integrations.msgraph import MSGraphClient
            client = MSGraphClient(db_path=db_path)
            all_slots.append(client.get_free_slots(date))
        elif cal == "google":
            from integrations.google_calendar import GoogleCalendarClient
            token = _get_google_token(db_path)
            if token:
                gcal = GoogleCalendarClient(access_token=token)
                all_slots.append(gcal.get_free_slots(date))

    # If only one source, return its slots directly
    if len(all_slots) <= 1:
        return {"date": date, "slots": all_slots[0] if all_slots else []}

    # Intersect free slots across sources (only times free in ALL calendars)
    from engine.slot_intersect import intersect_free_slots
    merged = intersect_free_slots(all_slots)
    return {"date": date, "slots": merged}


def _handle_end_call(arguments, db_path=None, **_kw):
    """Signal the call should be hung up."""
    return {
        "action": "hangup",
        "reason": arguments.get("reason", "unspecified"),
    }


# ── Dispatcher ─────────────────────────────────────────────────────────

_HANDLERS = {
    "check_availability": _handle_check_availability,
    "forward_call": _handle_forward_call,
    "take_message": _handle_take_message,
    "suggest_callback_times": _handle_suggest_callback_times,
    "end_call": _handle_end_call,
}


def execute_tool(tool_name, arguments, db_path=None, mock_presence=None):
    """Dispatch a tool call by name. Returns a result dict.

    Parameters
    ----------
    tool_name : str
        One of the registered tool names.
    arguments : dict
        Arguments parsed from the LLM's tool call.
    db_path : str | None
        SQLite path override (for testing).
    mock_presence : str | None
        If set, ``check_availability`` uses this instead of MS Graph.
    """
    handler = _HANDLERS.get(tool_name)
    if handler is None:
        return {"error": f"Unknown tool: {tool_name}"}
    return handler(arguments, db_path=db_path, mock_presence=mock_presence)
