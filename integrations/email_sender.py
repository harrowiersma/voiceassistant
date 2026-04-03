"""SMTP email sender for post-call summary notifications."""

import logging
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.helpers import get_config

logger = logging.getLogger(__name__)


class EmailSender:
    """Sends call summary emails via SMTP."""

    def __init__(self, db_path=None):
        self.db_path = db_path

    def _get_smtp_config(self):
        """Read all SMTP settings from config table. Returns dict or None."""
        server = get_config("actions.smtp_server", db_path=self.db_path)
        if not server:
            return None
        return {
            "server": server,
            "port": int(get_config("actions.smtp_port", "587", db_path=self.db_path)),
            "username": get_config("actions.smtp_username", db_path=self.db_path),
            "password": get_config("actions.smtp_password", db_path=self.db_path),
            "email_to": get_config("actions.email_to", db_path=self.db_path),
            "email_from": get_config("actions.email_from", db_path=self.db_path),
        }

    def _render_summary(self, caller_name, caller_number, reason, transcript, action_taken):
        """Return a formatted plain-text call summary."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return (
            f"Call Summary\n"
            f"{'=' * 40}\n\n"
            f"Time:         {timestamp}\n"
            f"Caller:       {caller_name}\n"
            f"Number:       {caller_number}\n"
            f"Reason:       {reason}\n"
            f"Action Taken: {action_taken}\n\n"
            f"Transcript\n"
            f"{'-' * 40}\n"
            f"{transcript}\n"
        )

    def send_call_summary(self, caller_name, caller_number, reason, transcript, action_taken):
        """Construct and send a call summary email. Returns True on success, False on failure."""
        cfg = self._get_smtp_config()
        if not cfg:
            logger.warning("SMTP not configured — skipping email notification")
            return False

        body = self._render_summary(caller_name, caller_number, reason, transcript, action_taken)

        msg = MIMEMultipart()
        msg["From"] = cfg["email_from"]
        msg["To"] = cfg["email_to"]
        msg["Subject"] = f"Call Summary: {caller_name} — {reason}"
        msg.attach(MIMEText(body, "plain"))

        try:
            with smtplib.SMTP(cfg["server"], cfg["port"]) as server:
                server.starttls()
                if cfg["username"] and cfg["password"]:
                    server.login(cfg["username"], cfg["password"])
                server.send_message(msg)
            logger.info("Call summary email sent to %s", cfg["email_to"])
            return True
        except Exception:
            logger.exception("Failed to send call summary email")
            return False
