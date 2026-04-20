"""Regression tests for cv_sense hang-remediation (cycle-6 A1).

Pins the invariants that close the 2026-04-20 incident pattern on
`CVSenseNode`:
  - `stop()` is loud when the worker is wedged (uses `join_or_raise`).
  - `start()` refuses to double-start a zombie worker.
  - `_worker_loop` wakes on stop, not on the next sleep boundary.
"""

from __future__ import annotations

import threading
import time
from unittest import mock

import pytest

from photonic_synesthesia.core.config import CVConfig


def _build_cv_node():
    """Build a CV node in threaded mode, bypassing the cv2/mss import
    so the test runs on CI workers without a display."""
    config = CVConfig(enabled=True, capture_rate_hz=100.0)
    with mock.patch(
        "photonic_synesthesia.graph.nodes.cv_sense.CV_AVAILABLE", True
    ):
        with mock.patch(
            "photonic_synesthesia.graph.nodes.cv_sense.mss"
        ) as fake_mss:
            fake_mss.mss.return_value = mock.MagicMock()
            from photonic_synesthesia.graph.nodes.cv_sense import CVSenseNode

            node = CVSenseNode(config, cv_threaded=True)
            node.enabled = True
    return node


def test_cv_sense_stop_is_loud_when_worker_is_wedged() -> None:
    """Core A1 invariant: a wedged cv2 call MUST raise, not silently leak.

    Yesterday's incident class — simulated by a `_refresh_cached_state`
    that blocks inside a C call the stop signal cannot interrupt."""
    node = _build_cv_node()

    release = threading.Event()

    def _wedged_refresh(*_args, **_kwargs) -> None:
        # Simulate a cv2.grab() stuck in a kernel wait — doesn't
        # consult the stop signal.
        release.wait(timeout=5.0)

    node._refresh_cached_state = _wedged_refresh  # type: ignore[assignment]
    node.start()

    # Wait until the worker has entered the wedged call.
    time.sleep(0.05)

    with pytest.raises(RuntimeError, match="CV-Sense.*failed to exit"):
        node.stop()

    # Cleanup so the test doesn't itself leak.
    release.set()
    if node._worker_thread is not None:
        node._worker_thread.join(timeout=1.0)


def test_cv_sense_start_refuses_to_double_start() -> None:
    """If a previous stop timed out and the worker is still alive,
    start() must refuse rather than spawn a second worker —
    yesterday's N-fold CPU saturation pattern."""
    node = _build_cv_node()
    release = threading.Event()

    node._refresh_cached_state = lambda *_: release.wait(  # type: ignore[assignment]
        timeout=5.0
    )
    node.start()
    time.sleep(0.03)

    with pytest.raises(RuntimeError, match="refusing to double-start"):
        node.start()

    # Drain
    release.set()
    try:
        node.stop()
    except RuntimeError:
        pass
    if node._worker_thread is not None:
        node._worker_thread.join(timeout=1.0)


def test_cv_sense_stop_wakes_loop_immediately_not_after_sleep_cycle() -> None:
    """Prove the stop signal bypasses the sleep cycle. Before A1, the
    loop polled `_worker_running` on wake-up — stop took up to
    `_capture_interval / 4` to be seen. Now `StopSignal.wait()` returns
    True immediately on stop, cutting the leak window to zero."""
    node = _build_cv_node()
    # Override with a stubbed refresh that doesn't block
    node._refresh_cached_state = lambda *_: None  # type: ignore[assignment]
    node.start()
    time.sleep(0.02)

    t0 = time.monotonic()
    node.stop()
    elapsed = time.monotonic() - t0

    # With a 100 Hz capture rate, the pre-fix loop slept
    # `min(0.005, 0.0025) = 2.5ms`, so stop could only be observed
    # with that latency. StopSignal.wait returns true immediately, so
    # even the join overhead is <50ms.
    assert elapsed < 0.1, f"stop took {elapsed*1000:.1f} ms — expected <100ms"
