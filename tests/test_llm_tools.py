import json
from unittest.mock import patch, MagicMock
import pytest
from engine.llm import LLMClient
from engine.tools import TOOL_DEFINITIONS

def _mock_response(response_data):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps(response_data).encode()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp

def test_chat_with_tools_sends_tools_in_request():
    client = LLMClient(model="llama3.2:1b")
    client._available = True
    captured = {}
    def mock_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data)
        return _mock_response({"message": {"role": "assistant", "content": "I'll check."}})
    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        client.chat("Is Harro available?", system_prompt="Secretary.", tools=TOOL_DEFINITIONS)
    assert "tools" in captured["body"]
    assert len(captured["body"]["tools"]) == len(TOOL_DEFINITIONS)

def test_chat_returns_tool_call_as_dict():
    client = LLMClient(model="llama3.2:1b")
    client._available = True
    response_data = {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "check_availability", "arguments": {}}}]
        }
    }
    with patch("urllib.request.urlopen", return_value=_mock_response(response_data)):
        result = client.chat("Is Harro available?", system_prompt="Test.", tools=TOOL_DEFINITIONS)
    assert isinstance(result, dict)
    assert "tool_calls" in result

def test_chat_without_tools_returns_string():
    client = LLMClient(model="llama3.2:1b")
    client._available = True
    response_data = {"message": {"role": "assistant", "content": "Hello! How can I help?"}}
    with patch("urllib.request.urlopen", return_value=_mock_response(response_data)):
        result = client.chat("Hello", system_prompt="Test")
    assert isinstance(result, str)
    assert "Hello" in result
