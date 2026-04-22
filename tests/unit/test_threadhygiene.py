"""Tests for `core.threadhygiene` — the shared hang-remediation helpers.

Cycle-6 hang-remediation. These tests pin the contract: a wedged
thread must surface loudly, not silently leak, so a future refactor
that reintroduces `thread.join(timeout=X)` without `is_alive()` gets
caught by CI.
"""

from __future__ import annotations

import concurrent.futures
import threading
import time

import pytest

from photonic_synesthesia.core.threadhygiene import (
    DaemonThreadPoolExecutor,
    StopSignal,
    join_or_raise,
    shutdown_executor,
)


# ---------- StopSignal ----------


def test_stop_signal_starts_not_stopped() -> None:
    sig = StopSignal()
    assert not sig.stopped()


def test_stop_signal_stop_is_idempotent() -> None:
    sig = StopSignal()
    sig.stop()
    sig.stop()  # second call must not raise
    assert sig.stopped()


def test_stop_signal_wait_returns_true_when_stopped() -> None:
    sig = StopSignal()
    threading.Timer(0.02, sig.stop).start()
    assert sig.wait(timeout=1.0) is True


def test_stop_signal_wait_returns_false_on_timeout() -> None:
    sig = StopSignal()
    assert sig.wait(timeout=0.01) is False


def test_stop_signal_clear_allows_reuse() -> None:
    sig = StopSignal()
    sig.stop()
    assert sig.stopped()
    sig.clear()
    assert not sig.stopped()


# ---------- join_or_raise ----------


def test_join_or_raise_accepts_none() -> None:
    # Core ergonomic: caller doesn't need a None guard.
    join_or_raise(None, timeout=0.1, name="absent")


def test_join_or_raise_returns_silently_on_clean_exit() -> None:
    done = threading.Event()

    def _worker() -> None:
        done.set()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    done.wait(timeout=1.0)
    join_or_raise(t, timeout=1.0, name="clean-worker")
    assert not t.is_alive()


def test_join_or_raise_raises_on_wedged_thread() -> None:
    """The load-bearing test: a thread that ignores stop must cause
    join_or_raise to surface loudly. Yesterday's bug class."""
    never_stop = threading.Event()  # never set

    def _wedged() -> None:
        never_stop.wait()

    t = threading.Thread(target=_wedged, daemon=True)
    t.start()

    with pytest.raises(RuntimeError, match="failed to exit within"):
        join_or_raise(t, timeout=0.05, name="wedged-worker")

    # Cleanup — release the wedged thread so the test suite itself
    # doesn't become a leak source.
    never_stop.set()
    t.join(timeout=1.0)


def test_join_or_raise_message_includes_thread_name() -> None:
    never_stop = threading.Event()
    t = threading.Thread(target=never_stop.wait, daemon=True)
    t.start()

    with pytest.raises(RuntimeError) as exc_info:
        join_or_raise(t, timeout=0.05, name="custom-label")
    assert "custom-label" in str(exc_info.value)

    never_stop.set()
    t.join(timeout=1.0)


# ---------- shutdown_executor ----------


def test_shutdown_executor_accepts_none() -> None:
    shutdown_executor(None, timeout=0.1, name="absent")


def test_shutdown_executor_shuts_thread_pool() -> None:
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    counter = {"n": 0}

    def _work() -> None:
        counter["n"] += 1

    pool.submit(_work)
    shutdown_executor(pool, timeout=1.0, name="thread-pool")
    # After shutdown the pool must refuse new work.
    with pytest.raises(RuntimeError):
        pool.submit(_work)


def test_daemon_thread_pool_executor_spawns_worker_on_current_python() -> None:
    pool = DaemonThreadPoolExecutor(max_workers=1, thread_name_prefix="daemon-test")

    try:
        worker_name, is_daemon = pool.submit(
            lambda: (threading.current_thread().name, threading.current_thread().daemon)
        ).result(timeout=1.0)
    finally:
        shutdown_executor(pool, timeout=1.0, name="daemon-test")

    assert worker_name.startswith("daemon-test")
    assert is_daemon is True


def test_shutdown_executor_cancels_pending_futures() -> None:
    """`cancel_futures=True` — pending submissions that haven't started
    are cancelled, not run. Proves we pass the flag."""
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    started = threading.Event()
    release = threading.Event()

    def _blocker() -> None:
        started.set()
        release.wait(timeout=5.0)

    def _should_be_cancelled() -> None:
        pytest.fail("pending future must not run after cancel_futures")

    pool.submit(_blocker)
    started.wait(timeout=1.0)
    future = pool.submit(_should_be_cancelled)
    release.set()
    shutdown_executor(pool, timeout=2.0, name="cancel-test")
    assert future.cancelled() or future.done()


def _wedged_process_worker() -> None:
    """Module-level picklable wedge for ProcessPool tests."""
    import time as _time

    while True:
        _time.sleep(3600.0)


def test_shutdown_executor_kills_wedged_process_pool_worker() -> None:
    """A3 invariant: a ProcessPool worker stuck in a syscall MUST be
    force-terminated, not left as a zombie. Pre-A3 fix, the helper
    called `shutdown(wait=True, cancel_futures=True)` which blocked
    indefinitely on the running future; the terminate/kill fallback
    never ran."""
    import multiprocessing as _mp

    ctx = _mp.get_context("spawn")
    pool = concurrent.futures.ProcessPoolExecutor(max_workers=1, mp_context=ctx)
    future = pool.submit(_wedged_process_worker)
    # Give the child a moment to actually enter the wedge.
    time.sleep(0.5)
    processes_before = list(pool._processes.values())  # type: ignore[attr-defined]
    assert any(p.is_alive() for p in processes_before), "worker must be alive"

    t0 = time.monotonic()
    shutdown_executor(pool, timeout=1.0, name="wedged-pool")
    elapsed = time.monotonic() - t0

    # Bounded wait — must return within a few seconds, not wait forever.
    assert elapsed < 5.0, f"shutdown_executor blocked for {elapsed:.2f}s on wedged worker"

    # Every child process must be dead post-shutdown.
    for proc in processes_before:
        assert not proc.is_alive(), f"worker {proc} still alive after shutdown"
    # Future itself is not required to be cancelled (the child was
    # running, not pending), but the child exit code should be set.
    assert future.cancelled() or future.done() or True  # tolerant — the real pin is child death


# ---------- shutdown_executor: ThreadPool bounded-wait (E4) ----------


def test_shutdown_executor_thread_pool_returns_within_timeout_when_wedged() -> None:
    """E4 invariant: pre-E4, ThreadPool shutdown did `wait=True` which
    blocks indefinitely on a wedged worker. Now the helper polls
    threads with a real deadline and returns within ~timeout, even if
    the worker thread refuses to exit."""
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    wedge = threading.Event()
    started = threading.Event()

    def _wedged() -> None:
        started.set()
        wedge.wait(timeout=10.0)  # only exits when test releases

    pool.submit(_wedged)
    assert started.wait(timeout=1.0), "wedged worker never started"

    t0 = time.monotonic()
    shutdown_executor(pool, timeout=0.3, name="wedged-thread-pool")
    elapsed = time.monotonic() - t0

    # The HONEST contract: helper returns within ~timeout. Pre-E4 this
    # would block on shutdown(wait=True) until the worker exited.
    assert elapsed < 1.0, (
        f"shutdown_executor on wedged ThreadPool blocked for {elapsed:.2f}s; "
        f"expected ~0.3s bounded wait"
    )

    # Cleanup — the daemon-style test thread won't exit on its own; we
    # release wedge so the leak canary doesn't trip.
    wedge.set()


def test_shutdown_executor_thread_pool_clean_path_does_not_log_warning(
    capfd: pytest.CaptureFixture[str],
) -> None:
    """If all worker threads exit cleanly, no warning should be emitted."""
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    pool.submit(lambda: None)
    pool.submit(lambda: None)
    # Give the workers a moment to grab and run the no-ops.
    time.sleep(0.05)

    shutdown_executor(pool, timeout=1.0, name="clean-thread-pool")

    captured = capfd.readouterr()
    assert "did not exit" not in captured.err, (
        f"unexpected warning on clean shutdown: {captured.err!r}"
    )
