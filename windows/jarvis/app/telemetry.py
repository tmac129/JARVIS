"""Telemetria leggera (un campione al secondo): CPU, memoria, batteria, rete."""
from __future__ import annotations

import time

import psutil


class Telemetry:
    def __init__(self):
        psutil.cpu_percent(interval=None)    # il primo campione non e' significativo: lo scarto
        n = psutil.net_io_counters()
        self._net = (n.bytes_recv, n.bytes_sent, time.time()) if n else None

    def sample(self) -> dict:
        vm = psutil.virtual_memory()
        b = psutil.sensors_battery()
        in_rate = out_rate = 0.0
        n = psutil.net_io_counters()
        now = time.time()
        if n and self._net:
            dt = max(now - self._net[2], 0.1)
            in_rate = max(0, n.bytes_recv - self._net[0]) / dt
            out_rate = max(0, n.bytes_sent - self._net[1]) / dt
        if n:
            self._net = (n.bytes_recv, n.bytes_sent, now)
        return {
            "type": "telemetry", "cpu": psutil.cpu_percent(interval=None),
            "ramUsed": vm.used / 1073741824, "ramTotal": vm.total / 1073741824,
            "batt": round(b.percent) if b else -1, "charging": bool(b and b.power_plugged and b.percent < 100),
            "ac": bool(b and b.power_plugged), "netIn": in_rate, "netOut": out_rate,
            "thermal": "--", "uptime": now - psutil.boot_time(),
        }
