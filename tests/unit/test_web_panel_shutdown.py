"""Regression tests for web_panel.shutdown_server (cycle-6 A4).

Pins the three-phase shutdown contract:
  - Soft: set should_exit, join(soft_timeout). Clean path.
  - Hard: if still alive, set force_exit, join(force_timeout).
  - Loud: if STILL alive, log error. Thread stays alive; we don't
    raise, because the thread is a daemon and we don't want the
    finally block to mask the original exception.
"""

from __future__ import annotations

import threading
import time
from unittest import mock

import pytest

from photonic_synesthesia.ui.web_panel import shutdown_server


class _FakeServer:
    def __init__(self) -> None:
        self.should_exit = False
        self.force_exit = False


def test_shutdown_server_accepts_none_for_either_arg() -> None:
    shutdown_server(None, None)
    shutdown_server(_FakeServer(), None)

    t = threading.Thread(target=lambda: None, daemon=True)
    t.start()
    t.join()
    shutdown_server(None, t)  # should not raise


def test_shutdown_server_soft_path_sets_should_exit_and_joins() -> None:
    server = _FakeServer()
    done = threading.Event()

    def _worker() -> None:
        # Simulate uvicorn: spin until should_exit, then exit.
        while not server.should_exit:
            time.sleep(0.01)
        done.set()

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()

    shutdown_server(server, thread, soft_timeout=2.0)

    assert server.should_exit is True
    assert server.force_exit is False, "force_exit only fires when soft times out"
    assert done.is_set()
    assert not thread.is_alive()


def test_shutdown_server_escalates_to_force_exit_when_soft_times_out() -> None:
    """Core A4 invariant: if the server ignores should_exit (a wedged
    request or websocket), force_exit must be set as the escalation."""
    server = _FakeServer()
    observed_force_exit = threading.Event()

    def _wedged_worker() -> None:
        # Only exit on force_exit — simulates a hung in-flight request.
        while not server.force_exit:
            time.sleep(0.01)
        observed_force_exit.set()

    thread = threading.Thread(target=_wedged_worker, daemon=True)
    thread.start()

    shutdown_server(server, thread, soft_timeout=0.1, force_timeout=2.0)

    assert server.should_exit is True
    assert server.force_exit is True
    assert observed_force_exit.is_set()
    assert not thread.is_alive()


def test_serve_in_thread_calls_shutdown_on_startup_failure() -> None:
    """Cycle-6 E5/H7: if the startup wait raises (timeout, port-bind
    failure, server thread terminating early), serve_in_thread MUST
    call shutdown_server before re-raising. Pre-E5 the daemon
    uvicorn thread leaked until process exit and held the port bound,
    blocking the operator's retry."""
    from photonic_synesthesia.ui import web_panel

    # Stand-in for uvicorn.Server: never flips `.started`, so the
    # startup wait hits the deadline. `.run()` returns immediately.
    fake_server = mock.MagicMock()
    fake_server.started = False
    fake_server.run = lambda: None

    fake_uvicorn = mock.MagicMock()
    fake_uvicorn.Config.return_value = mock.MagicMock()
    fake_uvicorn.Server.return_value = fake_server

    with (
        mock.patch.dict("sys.modules", {"uvicorn": fake_uvicorn}),
        mock.patch.object(web_panel, "create_app", return_value=mock.MagicMock()),
        mock.patch.object(web_panel, "shutdown_server") as fake_shutdown,
    ):
        # Jump time forward on each call so the 5s deadline arrives
        # in a few microseconds instead of hanging the test.
        time_now = [time.time()]

        def _fake_time() -> float:
            time_now[0] += 1.0
            return time_now[0]

        with mock.patch.object(web_panel.time, "time", _fake_time):
            with pytest.raises(RuntimeError, match="(Timed out waiting|terminated before startup)"):
                web_panel.serve_in_thread(host="127.0.0.1", port=0)

    fake_shutdown.assert_called_once()
    args, kwargs = fake_shutdown.call_args
    assert args[0] is fake_server
    assert isinstance(args[1], threading.Thread)
    assert args[1].daemon is True


def test_shutdown_server_logs_error_but_returns_when_both_timeouts_exhausted() -> None:
    """Yesterday's crash class: a hung websocket handler kept the
    server thread alive past both timeouts. We must NOT raise — the
    caller is inside a finally block that's cleaning up multiple
    resources. Just log loudly so the leak is visible."""
    server = _FakeServer()
    release = threading.Event()

    def _unkillable() -> None:
        # Ignores both should_exit and force_exit — models a wedged
        # C extension or kernel-level stall.
        release.wait(timeout=5.0)

    thread = threading.Thread(target=_unkillable, daemon=True)
    thread.start()

    with mock.patch("photonic_synesthesia.ui.web_panel.logger") as fake_log:
        shutdown_server(server, thread, soft_timeout=0.05, force_timeout=0.05)

    assert server.should_exit is True
    assert server.force_exit is True
    fake_log.error.assert_called_once()
    error_event = fake_log.error.call_args[0][0]
    assert "failed_to_exit" in error_event

    # Cleanup — release the thread so the test suite doesn't leak it.
    release.set()
    thread.join(timeout=1.0)
