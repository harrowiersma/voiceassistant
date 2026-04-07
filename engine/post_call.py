"""Post-call action engine: logs calls and sends email notifications."""

import json
import logging
from datetime import datetime

from app.helpers import get_config
from db.connection import get_db_connection
from integrations.email_sender import EmailSender

logger = logging.getLogger(__name__)


def log_call(db_path, caller_number, caller_name, reason, transcript, action_taken, duration_seconds=0):
    """Insert a call record into the database. Returns the new call ID."""
    if isinstance(transcript, list):
        transcript = json.dumps(transcript)

    conn = get_db_connection(db_path)
    cursor = conn.execute(
        """INSERT INTO calls
           (started_at, caller_number, caller_name, reason, transcript, action_taken, duration_seconds)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (datetime.now().isoformat(), caller_number, caller_name, reason, transcript, action_taken, duration_seconds),
    )
    conn.commit()
    call_id = cursor.lastrowid
    conn.close()
    return call_id


def process_post_call_actions(db_path, call_id, caller_name, caller_number, reason, transcript, action_taken, persona_name="Unknown", dialed_did="Unknown"):
    """Decide whether to send email based on config, then update the call record."""
    notify_on = get_config("actions.notify_on", "never", db_path=db_path)

    email_sent = False
    calendar_created = False

    should_email = False
    if notify_on == "all_calls":
        should_email = True
    elif notify_on == "message_only":
        should_email = action_taken in ("message_taken", "voicemail")

    if should_email:
        sender = EmailSender(db_path)
        email_sent = sender.send_call_summary(caller_name, caller_number, reason, transcript, action_taken, persona_name=persona_name, dialed_did=dialed_did)

    # Update the call record with action flags
    conn = get_db_connection(db_path)
    conn.execute(
        "UPDATE calls SET email_sent = ?, calendar_created = ? WHERE id = ?",
        (email_sent, calendar_created, call_id),
    )
    conn.commit()
    conn.close()

    return {"email_sent": email_sent, "calendar_created": calendar_created}
