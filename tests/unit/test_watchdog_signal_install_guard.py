"""Regression test for SIGUSR1 install guard (cycle-6 B5).

Pins:
  - Non-main-thread call logs at ERROR (not WARN) so the dropped
    soft-stall channel is visible in audit.
  - Main-thread call installs the handler normally and logs nothing.
"""

from __future__ import annotations

import signal
import threading
from unittest import mock


def _build_min_graph_for_watchdog_test() -> object:
    """Build the bare minimum state `_start_out_of_process_watchdog`
    needs — we're only testing the signal-install branch, not the
    full spawn path."""
    from photonic_synesthesia.graph.builder import PhotonicGraph

    graph = PhotonicGraph.__new__(PhotonicGraph)
    graph.nodes = {}
    graph._enable_watchdog = True
    graph._watchdog_proc = None
    graph._watchdog_shmem = None
    return graph


def test_sigusr1_install_in_main_thread_succeeds_and_does_not_log_error() -> None:
    """Happy path: in the main thread, the handler installs cleanly."""
    graph = _build_min_graph_for_watchdog_test()
    previous = signal.getsignal(signal.SIGUSR1)
    try:
        with (
            mock.patch(
                "photonic_watchdog.shmem.WatchdogSharedState",
                return_value=mock.MagicMock(),
            ),
            mock.patch("multiprocessing.get_context") as fake_get_context,
            mock.patch("photonic_synesthesia.graph.builder.logger") as fake_log,
        ):
            fake_ctx = fake_get_context.return_value
            fake_ctx.Process.return_value = mock.MagicMock()

            graph._start_out_of_process_watchdog()

        # Handler installed = current handler is now different.
        assert signal.getsignal(signal.SIGUSR1) != previous
        # No ERROR log — main-thread path is silent on this dimension.
        fake_log.error.assert_not_called()
    finally:
        signal.signal(signal.SIGUSR1, previous)


def test_sigusr1_install_in_non_main_thread_logs_error_and_skips_install() -> None:
    """Core B5 invariant: invocation from a worker thread must NOT
    call signal.signal (would raise ValueError) and MUST log at
    ERROR so the dropped soft-stall channel is visible."""
    graph = _build_min_graph_for_watchdog_test()
    signal_sigusr1_calls: list[object] = []
    error_event_captured: list[str] = []
    done = threading.Event()

    original_signal = signal.signal

    def _tracking_signal(sig: int, handler: object) -> object:
        if sig == signal.SIGUSR1:
            signal_sigusr1_calls.append(handler)
        return original_signal(sig, handler)  # type: ignore[arg-type]

    def _run_from_worker() -> None:
        try:
            with (
                mock.patch(
                    "photonic_watchdog.shmem.WatchdogSharedState",
                    return_value=mock.MagicMock(),
                ),
                mock.patch("multiprocessing.get_context") as fake_get_context,
                mock.patch("signal.signal", side_effect=_tracking_signal),
                mock.patch("photonic_synesthesia.graph.builder.logger") as fake_log,
            ):
                fake_ctx = fake_get_context.return_value
                fake_ctx.Process.return_value = mock.MagicMock()

                graph._start_out_of_process_watchdog()

                if fake_log.error.called:
                    event = fake_log.error.call_args[0][0]
                    error_event_captured.append(event)
        finally:
            done.set()

    worker = threading.Thread(target=_run_from_worker, name="B5-worker")
    worker.start()
    done.wait(timeout=5.0)
    worker.join(timeout=1.0)

    assert error_event_captured == ["sigusr1_install_skipped_non_main_thread"], (
        f"expected skipped-non-main-thread ERROR, got {error_event_captured}"
    )
    assert not signal_sigusr1_calls, (
        f"signal.signal(SIGUSR1, ...) must NOT be called from a worker thread; "
        f"got {signal_sigusr1_calls}"
    )
