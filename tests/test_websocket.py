import pytest


def test_broadcaster_tracks_active_calls():
    from app.websocket import CallStatusBroadcaster
    broadcaster = CallStatusBroadcaster()
    broadcaster.call_started("uuid-1", "+41791111111")
    assert broadcaster.active_calls == 1
    assert broadcaster.get_status()["active_calls"] == 1


def test_broadcaster_removes_ended_calls():
    from app.websocket import CallStatusBroadcaster
    broadcaster = CallStatusBroadcaster()
    broadcaster.call_started("uuid-1", "+41791111111")
    broadcaster.call_ended("uuid-1")
    assert broadcaster.active_calls == 0


def test_broadcaster_formats_status():
    from app.websocket import CallStatusBroadcaster
    broadcaster = CallStatusBroadcaster()
    broadcaster.call_started("uuid-1", "+41791234567")
    status = broadcaster.get_status()
    assert status["active_calls"] == 1
    assert "+41791234567" in str(status["calls"])
