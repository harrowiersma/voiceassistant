"""CallSession — manages one phone call's conversation flow.

Handles greeting, conversation turns with LLM tool calling,
silence detection, vacation mode, manual override, and call ending.
"""

import json
import logging
from datetime import datetime

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

        # Call LLM with tools
        result = self.llm.chat(
            caller_text,
            system_prompt=self.system_prompt,
            history=history,
            tools=TOOL_DEFINITIONS,
        )

        # Handle tool calls
        if isinstance(result, dict) and result.get("tool_calls"):
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
