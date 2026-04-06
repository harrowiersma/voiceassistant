import json
import logging

logger = logging.getLogger(__name__)

FALLBACK_RESPONSE = "I'm sorry, the AI assistant is not available right now. Please leave a message after the tone."


class LLMClient:
    def __init__(self, model="llama3.2:1b", base_url="http://localhost:11434"):
        self.model = model
        self.base_url = base_url
        self._available = None

    def is_available(self):
        if self._available is not None:
            return self._available
        try:
            import urllib.request
            req = urllib.request.Request(f"{self.base_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                self._available = resp.status == 200
        except Exception:
            self._available = False
        return self._available

    def chat(self, user_message, system_prompt="", history=None, tools=None):
        if not self.is_available():
            logger.warning("Ollama not available, returning fallback")
            return FALLBACK_RESPONSE
        try:
            import urllib.request
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            if history:
                messages.extend(history)
            messages.append({"role": "user", "content": user_message})
            body = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {
                    "num_predict": 80,  # Max ~2 sentences (keep responses short for phone)
                    "temperature": 0.7,
                },
            }
            if tools:
                body["tools"] = tools
            data = json.dumps(body).encode()
            req = urllib.request.Request(
                f"{self.base_url}/api/chat", data=data,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read())
                message = result["message"]
                if message.get("tool_calls"):
                    return message
                return message["content"]
        except Exception as e:
            logger.error(f"LLM chat error: {e}")
            return FALLBACK_RESPONSE
