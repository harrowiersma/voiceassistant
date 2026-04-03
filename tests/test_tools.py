"""Tests for engine/tools.py — LLM tool definitions and dispatcher."""
import json
import pytest
from engine.tools import TOOL_DEFINITIONS, execute_tool


def test_tool_definitions_are_valid():
    for tool in TOOL_DEFINITIONS:
        assert tool["type"] == "function"
        assert "name" in tool["function"]
        assert "description" in tool["function"]
        assert "parameters" in tool["function"]


def test_all_expected_tools_defined():
    names = {t["function"]["name"] for t in TOOL_DEFINITIONS}
    assert "check_availability" in names
    assert "forward_call" in names
    assert "take_message" in names
    assert "suggest_callback_times" in names
    assert "end_call" in names


def test_execute_check_availability():
    result = execute_tool("check_availability", {}, db_path=None, mock_presence="available")
    assert result["status"] == "available"
    assert result["action"] == "forward"


def test_execute_take_message():
    result = execute_tool("take_message", {
        "caller_name": "John Smith",
        "reason": "Project discussion",
        "callback_requested": True,
    }, db_path=None)
    assert result["success"] is True
    assert result["caller_name"] == "John Smith"


def test_execute_end_call():
    result = execute_tool("end_call", {"reason": "caller_goodbye"}, db_path=None)
    assert result["action"] == "hangup"


def test_execute_unknown_tool():
    result = execute_tool("nonexistent_tool", {}, db_path=None)
    assert "error" in result
