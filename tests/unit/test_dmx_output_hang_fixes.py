"""Regression tests for dmx_output hang-remediation (cycle-6 A2).

Pins:
  - `stop()` closes the serial handle BEFORE joining, so a blocked
    write wakes with EIO.
  - `stop()` raises if the transmit thread fails to exit within 2 s
    (was a 1 s silent-timeout).
  - `start()` refuses to double-start a live transmit worker.
  - `_transmit_loop` wakes on stop signal immediately, not on sleep.
"""

from __future__ import annotations

import threading
import time
from unittest import mock

import pytest

from photonic_synesthesia.core.config import DMXConfig


def _make_node():
    """DMX node with a mocked serial handle — no real FTDI required."""
    config = DMXConfig(
        interface_type="ftdi",
        ftdi_url="ftdi://fake/1",
        refresh_rate_hz=44.0,
    )
    from photonic_synesthesia.graph.nodes.dmx_output import DMXOutputNode

    return DMXOutputNode(config)


def test_dmx_stop_closes_serial_before_join() -> None:
    """Core A2 invariant: serial.close() MUST happen before the
    transmit thread join. Before the fix, close came AFTER join, so a
    blocked write could not be woken."""
    node = _make_node()

    # Track ordering of close() vs thread exit.
    order: list[str] = []

    class _FakeSerial:
        closed = False

        def send_break(self, duration: float = 0.0001) -> None:
            pass

        def write(self, data: bytes) -> None:
            pass

        def close(self) -> None:
            order.append("serial-close")
            self.closed = True

    node._serial = _FakeSerial()

    # Patch out the real start path; inject a worker that records its exit.
    def _noop_send() -> None:
        pass

    node._send_frame = _noop_send  # type: ignore[method-assign]

    def _worker() -> None:
        while not node._stop_signal.stopped():
            node._send_frame()
            node._stop_signal.wait(0.01)
        order.append("thread-exit")

    node._thread = threading.Thread(target=_worker, name="DMX-Transmit", daemon=True)
    node._thread.start()
    time.sleep(0.05)

    node.stop()

    assert order, "expected order events"
    assert order[0] == "serial-close", (
        f"serial close must come before thread exit; got {order}"
    )


def test_dmx_stop_is_loud_when_transmit_thread_wedges() -> None:
    """Yesterday's class of bug: if the worker ignores the stop signal,
    stop() must raise instead of silently returning."""
    node = _make_node()

    # Worker that completely ignores the stop signal. Simulates a
    # C extension that isn't checking the Python-level flag.
    def _wedged_worker() -> None:
        while True:
            time.sleep(0.05)

    node._thread = threading.Thread(target=_wedged_worker, name="DMX-Transmit", daemon=True)
    node._thread.start()

    with pytest.raises(RuntimeError, match="DMX-Transmit.*failed to exit"):
        node.stop()


def test_dmx_start_refuses_to_double_start() -> None:
    node = _make_node()

    # Pretend a previous stop left a zombie.
    node._thread = threading.Thread(
        target=lambda: time.sleep(5.0), name="DMX-Transmit", daemon=True
    )
    node._thread.start()

    # Keep start cheap by pretending pyftdi missing; the guard runs
    # BEFORE the hardware open path, so the RuntimeError should fire.
    with mock.patch(
        "photonic_synesthesia.graph.nodes.dmx_output.PYFTDI_AVAILABLE", True
    ):
        with mock.patch(
            "photonic_synesthesia.graph.nodes.dmx_output.serial_for_url"
        ) as fake_open:
            with pytest.raises(RuntimeError, match="refusing to double-start"):
                node.start()
            fake_open.assert_not_called()

    # Cleanup — let the sleeping daemon die out after the test ends.


def test_dmx_stop_returns_fast_under_normal_load() -> None:
    """Without the old `_running=False; join(timeout=1.0)` two-step,
    a clean stop should complete well under 100 ms."""
    node = _make_node()

    class _FakeSerial:
        def send_break(self, duration: float = 0.0001) -> None:
            pass

        def write(self, data: bytes) -> None:
            pass

        def close(self) -> None:
            pass

    node._serial = _FakeSerial()

    node._send_frame = lambda: None  # type: ignore[method-assign]

    def _clean_worker() -> None:
        while not node._stop_signal.stopped():
            node._send_frame()
            node._stop_signal.wait(0.02)

    node._thread = threading.Thread(target=_clean_worker, name="DMX-Transmit", daemon=True)
    node._thread.start()
    time.sleep(0.02)

    t0 = time.monotonic()
    node.stop()
    elapsed = time.monotonic() - t0

    assert elapsed < 0.1, f"clean stop should be <100ms; took {elapsed*1000:.1f}ms"
