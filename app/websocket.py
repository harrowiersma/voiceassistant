import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class CallStatusBroadcaster:
    def __init__(self):
        self._calls = {}

    @property
    def active_calls(self):
        return len(self._calls)

    def call_started(self, call_uuid, caller_number):
        self._calls[str(call_uuid)] = {
            "uuid": str(call_uuid),
            "caller_number": caller_number,
            "started_at": datetime.now().isoformat(),
            "state": "ringing",
        }

    def call_state_changed(self, call_uuid, state):
        key = str(call_uuid)
        if key in self._calls:
            self._calls[key]["state"] = state

    def call_ended(self, call_uuid):
        key = str(call_uuid)
        self._calls.pop(key, None)

    def get_status(self):
        return {"active_calls": self.active_calls, "calls": list(self._calls.values())}


# Singleton
call_status = CallStatusBroadcaster()
