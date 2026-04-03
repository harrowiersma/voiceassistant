import pytest
from engine.thermal import ThermalMonitor

def test_normal_temp_no_action():
    monitor = ThermalMonitor()
    assert monitor.check(55.0) is None

def test_warning_temp():
    monitor = ThermalMonitor()
    assert monitor.check(75.0) == "warning"

def test_critical_temp_downgrade():
    monitor = ThermalMonitor()
    assert monitor.check(82.0) == "downgrade"
    assert monitor.downgraded is True

def test_cooldown_restores():
    monitor = ThermalMonitor()
    monitor.check(82.0)
    assert monitor.downgraded is True
    for _ in range(3):
        monitor.check(60.0)
    assert monitor.downgraded is False
