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

    # Worker ignores the StopSignal and only exits when the test
    # releases `wedge` — that way the leak canary sees the thread
    # die after the assertion. A truly-infinite `while True:
    # time.sleep()` thread would leak past the test and trip the
    # canary.
    wedge = threading.Event()

    def _wedged_worker() -> None:
        wedge.wait(timeout=5.0)

    worker = threading.Thread(target=_wedged_worker, name="DMX-Transmit", daemon=True)
    worker.start()
    node._thread = worker

    try:
        with pytest.raises(RuntimeError, match="DMX-Transmit.*failed to exit"):
            node.stop()
    finally:
        # `stop()` nulls `node._thread` in its finally block, so we
        # keep our own reference to drain the wedged worker.
        wedge.set()
        worker.join(timeout=1.0)


def test_dmx_artnet_stop_still_blackouts_and_closes_when_join_raises() -> None:
    """Art-Net receivers need the final zero frame even if the worker wedged."""
    from photonic_synesthesia.core.config import DMXConfig
    from photonic_synesthesia.graph.nodes.dmx_output import DMXOutputNode

    node = DMXOutputNode(DMXConfig(interface_type="artnet"))
    wedge = threading.Event()
    worker = threading.Thread(target=lambda: wedge.wait(5.0), name="DMX-Transmit", daemon=True)
    worker.start()
    node._thread = worker
    artnet = mock.MagicMock()
    node._artnet = artnet

    try:
        with pytest.raises(RuntimeError, match="DMX-Transmit.*failed to exit"):
            node.stop()
    finally:
        wedge.set()
        worker.join(timeout=1.0)

    artnet.send_dmx.assert_called_once()
    artnet.close.assert_called_once()
    assert node._artnet is None


def test_dmx_start_refuses_to_double_start() -> None:
    node = _make_node()

    # Pretend a previous stop left a zombie. Use a releaseable Event
    # so the leak canary sees the thread die post-test (unbounded
    # `time.sleep(5)` would span multiple tests and trip the canary
    # on the NEXT test in the file).
    release = threading.Event()
    node._thread = threading.Thread(
        target=lambda: release.wait(timeout=5.0),
        name="DMX-Transmit",
        daemon=True,
    )
    node._thread.start()

    try:
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
    finally:
        release.set()
        if node._thread is not None:
            node._thread.join(timeout=1.0)


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
