"""Regression tests for safety_interlock hang-remediation (cycle-6 B1).

Pins both watchdogs (`HeartbeatWatchdog` and `SafetyMonitor`) against:
  - silent-zombie stop (now `join_or_raise`, raises on wedge)
  - double-start spawning a second daemon (now refuses)
  - stop() waking up on the next sleep boundary (now immediate)
"""

from __future__ import annotations

import threading
import time
from unittest import mock

import pytest

from photonic_synesthesia.graph.nodes.safety_interlock import (
    HeartbeatWatchdog,
    SafetyMonitor,
)


# ----------- HeartbeatWatchdog -----------


def test_heartbeat_watchdog_refuses_to_double_start() -> None:
    wd = HeartbeatWatchdog(on_timeout=lambda: None, timeout_s=1.0)
    wd.start()
    try:
        with pytest.raises(RuntimeError, match="refusing to double-start"):
            wd.start()
    finally:
        wd.stop()


def test_heartbeat_watchdog_stop_wakes_loop_immediately_not_after_sleep() -> None:
    """Pre-B1 the loop polled `_running` only after `time.sleep(0.1)`.
    With StopSignal.wait this is bounded by signal latency (~µs)."""
    wd = HeartbeatWatchdog(on_timeout=lambda: None, timeout_s=10.0, check_interval_s=0.5)
    wd.start()
    time.sleep(0.05)

    t0 = time.monotonic()
    wd.stop()
    elapsed = time.monotonic() - t0
    assert elapsed < 0.2, f"stop took {elapsed*1000:.1f}ms — expected <200ms"


def test_heartbeat_watchdog_stop_is_loud_when_worker_wedged() -> None:
    """If the watchdog's on_timeout callback wedges (e.g., a blackout
    that blocks on a closed handle), stop() must surface loudly."""
    wedge = threading.Event()
    # Worker thread that never looks at the stop signal — simulates a
    # C extension inside the callback.
    wd = HeartbeatWatchdog(on_timeout=lambda: None, timeout_s=1.0)
    worker = threading.Thread(
        target=lambda: wedge.wait(5.0), name="Heartbeat-Watchdog", daemon=True
    )
    worker.start()
    wd._thread = worker

    try:
        with pytest.raises(RuntimeError, match="Heartbeat-Watchdog.*failed to exit"):
            wd.stop()
    finally:
        # stop() nulls wd._thread in its finally; keep our own ref.
        wedge.set()
        worker.join(timeout=1.0)


# ----------- SafetyMonitor -----------


def _make_mock_output(running: bool = True) -> mock.MagicMock:
    m = mock.MagicMock()
    m.get_stats.return_value = {"running": running, "frames_sent": 0}
    return m


def test_safety_monitor_refuses_to_double_start() -> None:
    monitor = SafetyMonitor(dmx_output=_make_mock_output(), check_interval=0.05)
    monitor.start()
    try:
        with pytest.raises(RuntimeError, match="refusing to double-start"):
            monitor.start()
    finally:
        monitor.stop()


def test_safety_monitor_stop_returns_fast() -> None:
    """Pre-B1 sleep(check_interval) meant stop waited one interval.
    With StopSignal.wait it's immediate."""
    monitor = SafetyMonitor(dmx_output=_make_mock_output(), check_interval=0.5)
    monitor.start()
    time.sleep(0.02)

    t0 = time.monotonic()
    monitor.stop()
    elapsed = time.monotonic() - t0
    assert elapsed < 0.2, f"stop took {elapsed*1000:.1f}ms — expected <200ms"


def test_safety_monitor_stop_is_loud_when_worker_wedged() -> None:
    monitor = SafetyMonitor(dmx_output=_make_mock_output(), check_interval=0.05)
    wedge = threading.Event()
    # Replace worker thread with an unkillable one.
    worker = threading.Thread(
        target=lambda: wedge.wait(5.0), name="Safety-Monitor", daemon=True
    )
    worker.start()
    monitor._thread = worker

    try:
        with pytest.raises(RuntimeError, match="Safety-Monitor.*failed to exit"):
            monitor.stop()
    finally:
        wedge.set()
        worker.join(timeout=1.0)
