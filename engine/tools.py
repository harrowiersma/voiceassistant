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


def _handle_check_availability(arguments, db_path=None, mock_presence=None):
    """Check Teams presence; use *mock_presence* in tests."""
    if mock_presence is not None:
        status = mock_presence
    else:
        from integrations.msgraph import MSGraphClient
        client = MSGraphClient(db_path=db_path)
        status = client.check_presence()

    return {
        "status": status,
        "action": _PRESENCE_ACTION.get(status, "take_message"),
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


def _handle_suggest_callback_times(arguments, db_path=None, **_kw):
    """Query MS Graph for free calendar slots."""
    date = arguments.get("date") or datetime.utcnow().strftime("%Y-%m-%d")
    from integrations.msgraph import MSGraphClient
    client = MSGraphClient(db_path=db_path)
    slots = client.get_free_slots(date)
    return {"date": date, "slots": slots}


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
