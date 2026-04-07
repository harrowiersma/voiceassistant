"""CallSession — manages one phone call's conversation flow.

Handles greeting, conversation turns with LLM tool calling,
silence detection, vacation mode, manual override, and call ending.
"""

import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from app.helpers import get_config
from db.connection import get_db_connection
from engine.llm import LLMClient
from engine.prompt_builder import build_system_prompt, build_system_prompt_for_persona, get_active_vacation
from engine.tools import TOOL_DEFINITIONS, execute_tool

logger = logging.getLogger(__name__)


class CallSession:
    """State machine for a single inbound phone call."""

    def __init__(self, caller_number, db_path=None, persona_id=None):
        self.caller_number = caller_number
        self.db_path = db_path
        self.persona_id = persona_id
        self.persona = None
        self.state = "greeting"
        self.transcript = []
        self.started_at = datetime.now()
        self.silence_count = 0
        self.caller_name = None
        self.reason = None
        self.action_taken = None

        # Load persona from DB if persona_id provided
        if persona_id is not None:
            conn = get_db_connection(db_path)
            row = conn.execute("SELECT * FROM personas WHERE id = ?", (persona_id,)).fetchone()
            conn.close()
            if row:
                self.persona = dict(row)

        # Load system prompt — persona-specific or config-based
        if self.persona:
            self.system_prompt = build_system_prompt_for_persona(persona_id, db_path)
        else:
            self.system_prompt = build_system_prompt(db_path)

        model = get_config("ai.llm_model", default="llama3.2:1b", db_path=db_path)
        self.llm = LLMClient(model=model)

        # Check vacation
        vacation = get_active_vacation(db_path)
        self.vacation_active = vacation is not None
        self.vacation_message = vacation["response"] if vacation else None

        # Check manual override
        override = get_config("availability.manual_override", default="auto", db_path=db_path)
        self.forced_unavailable = (override == "unavailable")
        self.forced_available = (override == "available")

        # Check business hours (when override is "auto")
        # Uses the persona's timezone so Swiss calls check CET, Portugal checks WET, etc.
        self.outside_hours = False
        self.persona_tz_name = None
        if override == "auto":
            try:
                # Determine timezone from persona, fall back to server local time
                tz = None
                if self.persona and self.persona.get("timezone"):
                    try:
                        tz = ZoneInfo(self.persona["timezone"])
                        self.persona_tz_name = self.persona["timezone"]
                    except Exception:
                        pass
                now = datetime.now(tz) if tz else datetime.now()

                start_str = get_config("availability.business_hours_start", "09:00", db_path)
                end_str = get_config("availability.business_hours_end", "17:00", db_path)
                start_h, start_m = map(int, start_str.split(":"))
                end_h, end_m = map(int, end_str.split(":"))
                start_mins = start_h * 60 + start_m
                end_mins = end_h * 60 + end_m
                now_mins = now.hour * 60 + now.minute
                # Also check weekends (Saturday=5, Sunday=6)
                if now.weekday() >= 5 or now_mins < start_mins or now_mins >= end_mins:
                    self.outside_hours = True
                logger.info(f"Business hours check: tz={self.persona_tz_name or 'local'} "
                            f"now={now.strftime('%H:%M %Z %a')} hours={start_str}-{end_str} "
                            f"outside={self.outside_hours}")
            except Exception:
                pass  # If parsing fails, assume open

    def get_greeting_text(self):
        """Return the greeting with {company} substituted."""
        if self.persona:
            greeting = self.persona.get("greeting", "Hello.")
            company = self.persona.get("company_name", "")
            return greeting.replace("{company}", company)
        greeting = get_config("persona.greeting", default="Hello.", db_path=self.db_path)
        company = get_config("persona.company_name", default="", db_path=self.db_path)
        return greeting.replace("{company}", company)

    def process_turn(self, caller_text, mock_presence=None):
        """Process one caller utterance and return the assistant's response text.

        Parameters
        ----------
        caller_text : str
            Transcribed speech from the caller (empty string = silence).
        mock_presence : str | None
            If set, passed through to ``execute_tool`` for testing.
        """
        # Handle silence
        if not caller_text.strip():
            self.silence_count += 1
            if self.silence_count >= 3:
                self.state = "ending"
                return "I haven't heard anything. I'll hang up now. Goodbye."
            return "Are you still there? I didn't catch that."

        self.silence_count = 0
        self.transcript.append({"role": "user", "text": caller_text})

        # Build LLM history from prior transcript entries
        history = [
            {
                "role": "user" if t["role"] == "user" else "assistant",
                "content": t["text"],
            }
            for t in self.transcript[:-1]
        ]

        # Call LLM (no tool calling — Llama 3.2 1B doesn't support it reliably)
        # The system prompt instructs the AI on the conversation flow instead.
        result = self.llm.chat(
            caller_text,
            system_prompt=self.system_prompt,
            history=history,
        )

        # The result is always a string (natural language response)
        # Detect intent from the response text for call actions
        if isinstance(result, dict) and result.get("tool_calls"):
            # In case a larger model does return tool calls
            tool_results = []
            for tc in result["tool_calls"]:
                func = tc["function"]
                tr = execute_tool(
                    func["name"],
                    func.get("arguments", {}),
                    db_path=self.db_path,
                    mock_presence=mock_presence,
                )
                tool_results.append(tr)

                # Track actions from tool results
                if tr.get("action") == "forward":
                    self.action_taken = "forwarded"
                elif tr.get("action") == "hangup":
                    self.state = "ending"
                elif tr.get("success") and func["name"] == "take_message":
                    self.caller_name = tr.get("caller_name")
                    self.reason = tr.get("reason")
                    self.action_taken = "message_taken"

            # Get natural language response from LLM using tool results
            tool_context = json.dumps(tool_results)
            history.append({"role": "user", "content": caller_text})
            history.append({"role": "assistant", "content": f"[Tool results: {tool_context}]"})
            response_text = self.llm.chat(
                f"Based on these tool results, respond naturally to the caller: {tool_context}",
                system_prompt=self.system_prompt,
                history=history,
            )
        else:
            response_text = result if isinstance(result, str) else str(result)

        self.transcript.append({"role": "assistant", "text": response_text})
        return response_text

    def handle_action(self, tool_result):
        """Translate a tool result dict into a telephony action.

        Returns a dict with ``type`` ("forward", "hangup", or "continue")
        and any extra fields needed by the SIP layer.
        """
        action = tool_result.get("action")
        if action == "forward":
            self.state = "forwarding"
            self.action_taken = "forwarded"
            return {"type": "forward", "number": tool_result.get("number")}
        elif action == "hangup":
            self.state = "ending"
            return {"type": "hangup"}
        return {"type": "continue"}

    def end_call(self, reason="ended"):
        """Finalise the call and return a summary dict."""
        self.state = "ending"
        duration = int((datetime.now() - self.started_at).total_seconds())
        return {
            "caller_number": self.caller_number,
            "caller_name": self.caller_name or "Unknown",
            "reason": self.reason or reason,
            "transcript": self.transcript,
            "action_taken": self.action_taken or "ended",
            "duration_seconds": duration,
        }
