"""Regression test for watchdog subprocess shutdown escalation (cycle-6 B3).

Pre-B3 the graph stop path was `terminate()` + `join(timeout=2.0)` with
no post-join liveness check. A watchdog stuck in a shmem read (or
ignoring SIGTERM for any other reason) left a zombie subprocess
holding the shmem segment open. The unlink ran but the segment stayed
visible in `/dev/shm` until the zombie reaped.

B3 escalates to SIGKILL on soft-join timeout.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from photonic_synesthesia.graph.builder import PhotonicGraph


def _make_graph_with_fake_watchdog(
    *, is_alive_after_term: bool, is_alive_after_kill: bool = False
) -> tuple[PhotonicGraph, MagicMock]:
    """Build a minimal graph with a mocked watchdog subprocess.

    We bypass the normal `build_photonic_graph` path to avoid bringing
    up librosa / DSP just to test shutdown behavior.
    """
    graph = PhotonicGraph.__new__(PhotonicGraph)
    graph.nodes = {}
    graph.safety_monitor = None
    graph._running = True
    graph._enable_watchdog = True
    graph._tick_number = 0
    graph._watchdog_shmem = None

    fake_proc = MagicMock()
    fake_proc.pid = 99999
    alive_sequence = iter([is_alive_after_term, is_alive_after_kill])
    fake_proc.is_alive.side_effect = lambda: next(alive_sequence, False)
    graph._watchdog_proc = fake_proc
    return graph, fake_proc


def test_watchdog_clean_sigterm_does_not_escalate_to_kill() -> None:
    """Happy path: terminate() then join() returns cleanly — kill() must NOT run."""
    graph, fake_proc = _make_graph_with_fake_watchdog(is_alive_after_term=False)

    with patch("photonic_synesthesia.graph.builder.logger") as fake_log:
        graph.stop()

    fake_proc.terminate.assert_called_once()
    fake_proc.join.assert_called_once_with(timeout=2.0)
    fake_proc.kill.assert_not_called()
    fake_log.warning.assert_not_called()
    fake_log.error.assert_not_called()
    assert graph._watchdog_proc is None


def test_watchdog_ignoring_sigterm_escalates_to_sigkill_and_logs() -> None:
    """Core B3 invariant: if SIGTERM is ignored, kill() MUST run."""
    graph, fake_proc = _make_graph_with_fake_watchdog(
        is_alive_after_term=True,  # SIGTERM ignored
        is_alive_after_kill=False,  # SIGKILL wins
    )

    with patch("photonic_synesthesia.graph.builder.logger") as fake_log:
        graph.stop()

    fake_proc.terminate.assert_called_once()
    fake_proc.kill.assert_called_once()
    # Two join calls: one after terminate (timeout=2.0), one after kill (timeout=0.5)
    assert fake_proc.join.call_count == 2
    assert fake_proc.join.call_args_list[1].kwargs == {"timeout": 0.5}
    # Must warn about the escalation, not silently swallow.
    fake_log.warning.assert_called_once()
    warn_event = fake_log.warning.call_args[0][0]
    assert "escalating_to_sigkill" in warn_event
    # Clean exit after SIGKILL — no error log.
    fake_log.error.assert_not_called()
    assert graph._watchdog_proc is None


def test_watchdog_survives_sigkill_logs_error_but_still_clears_handle() -> None:
    """Yesterday's crash class: even SIGKILL can't reap a process stuck
    in uninterruptible D-state (kernel stall). Log loudly but don't hang."""
    graph, fake_proc = _make_graph_with_fake_watchdog(
        is_alive_after_term=True, is_alive_after_kill=True
    )

    with patch("photonic_synesthesia.graph.builder.logger") as fake_log:
        graph.stop()

    fake_proc.kill.assert_called_once()
    fake_log.error.assert_called_once()
    error_event = fake_log.error.call_args[0][0]
    assert "survived_sigkill" in error_event
    # Even when the SIGKILL escalation failed, the handle must be
    # cleared — otherwise a re-start() would try to double-handle a
    # zombie.
    assert graph._watchdog_proc is None
