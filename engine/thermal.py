TEMP_WARNING = 70.0
TEMP_CRITICAL = 80.0
COOLDOWN_READINGS = 3


class ThermalMonitor:
    def __init__(self):
        self.downgraded = False
        self._cool_count = 0

    def check(self, cpu_temp):
        if cpu_temp is None:
            return None
        if cpu_temp >= TEMP_CRITICAL:
            self.downgraded = True
            self._cool_count = 0
            return "downgrade"
        elif cpu_temp >= TEMP_WARNING:
            self._cool_count = 0
            return "warning"
        else:
            if self.downgraded:
                self._cool_count += 1
                if self._cool_count >= COOLDOWN_READINGS:
                    self.downgraded = False
                    self._cool_count = 0
            return None
