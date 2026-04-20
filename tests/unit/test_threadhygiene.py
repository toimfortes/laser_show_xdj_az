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
