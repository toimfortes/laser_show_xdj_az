"""Thread-hygiene primitives for graph nodes + executors.

Cycle-6 hang-remediation (see docs/superpowers/plans/
2026-04-20-hang-remediation-plan.md). Yesterday's system hang was caused
by `thread.join(timeout=X)` silently returning while the thread was still
alive — the daemon thread kept spinning on a closed shmem segment,
saturated CPU, and rtkit demoted every realtime thread in the system.

This module replaces the two anti-patterns that caused it:

  1. `self._running = bool` as a stop signal — wake-up waits on the next
     sleep cycle (up to `check_interval` ms), widening the leak window
     AND is non-atomic on some platforms.
     Replacement: `StopSignal` wraps `threading.Event` with a greppable
     name so a future reviewer catches a regression.

  2. `thread.join(timeout=X)` with no post-join liveness check — a 1 s
     timeout on a thread wedged in a C extension returns silently; the
     caller proceeds assuming the thread exited. Test-suite
     cumulative leak = yesterday's crash.
     Replacement: `join_or_raise()` — raises RuntimeError if the thread
     is still alive after the timeout. The failure is loud, per-test,
     and bisectable.

Executor lifecycle is analogously covered by `shutdown_executor()`.
"""

from __future__ import annotations

import concurrent.futures
import threading
from typing import Any


class StopSignal:
    """Tight wrapper around `threading.Event`.

    Exists as a distinct named type so the `self._running = bool`
    anti-pattern lights up under a simple grep. Also gives us a single
    place to instrument (e.g., log every `.stop()` call during a hang
    investigation) without touching every caller.
    """

    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = threading.Event()

    def stop(self) -> None:
        """Signal the owning loop to exit. Idempotent."""
        self._event.set()

    def stopped(self) -> bool:
        """True once `stop()` has been called."""
        return self._event.is_set()

    def wait(self, timeout: float) -> bool:
        """Sleep for `timeout` seconds OR until stopped — whichever comes
        first. Returns True if stopped, False on timeout. Replaces
        `time.sleep(check_interval)` in worker loops so the loop wakes
        immediately on stop, not on the next sleep boundary."""
        return self._event.wait(timeout)

    def clear(self) -> None:
        """Reset for reuse. Callers that start + stop + re-start the
        same worker should call this between cycles."""
        self._event.clear()


def join_or_raise(
    thread: threading.Thread | None,
    *,
    timeout: float,
    name: str,
) -> None:
    """Join a thread and RAISE if it's still alive after the timeout.

    This is the single function that eliminates the class of silent
    zombie-daemon bugs. Call it instead of `thread.join(timeout=...)`
    anywhere a test or runtime shutdown depends on the worker actually
    exiting.

    If `thread is None`, returns silently (makes the call-site
    one-liner clean: the caller doesn't need to pre-guard None).
    """
    if thread is None:
        return
    thread.join(timeout=timeout)
    if thread.is_alive():
        raise RuntimeError(
            f"Thread {name!r} failed to exit within {timeout}s "
            f"(is_alive=True after join). This indicates a wedged "
            f"worker — see docs/superpowers/plans/"
            f"2026-04-20-hang-remediation-plan.md for escalation."
        )


def shutdown_executor(
    executor: concurrent.futures.Executor | None,
    *,
    timeout: float,
    name: str,
) -> None:
    """Shutdown a ProcessPool/ThreadPoolExecutor with a real bounded
    wait. On timeout, escalates to terminate() then kill() on any
    child processes still alive (ProcessPool only — threads cannot be
    terminated). Passing `executor=None` is safe (no-op).

    ## ProcessPool path

    1. Snapshot `_processes.values()` BEFORE calling shutdown.  Newer
       CPython clears `_processes` inside `shutdown(wait=False,
       cancel_futures=True)`, which previously meant the terminate/kill
       loop iterated an empty dict and every wedged child survived
       (caught by `test_shutdown_executor_kills_wedged_process_pool_worker`).
    2. `shutdown(wait=False, cancel_futures=True)` so we don't block
       on the queue-management thread waiting for a wedged future.
    3. For each snapshotted child: bounded `join(timeout/2)`, then
       `.terminate()` + `join(timeout/2)`, then `.kill()` + `join(0.5)`.
    4. Final `shutdown(wait=True, cancel_futures=True)` lets the
       executor's `_queue_management_thread` exit cleanly now that
       children are dead. Without it, Python's module-level atexit in
       `concurrent.futures.process` blocks at interpreter shutdown
       trying to join a thread that is itself waiting on a now-dead
       child (caught as an 8-minute post-suite hang in cycle-6).

    ## ThreadPool path (cycle-6 E4/H2)

    Threads cannot be terminated. Pre-E4 we did `shutdown(wait=True,
    cancel_futures=True)` — but if a worker is wedged inside a deep
    Python call, `wait=True` blocks indefinitely. The helper's
    "bounded wait" promise was a lie for ThreadPool.

    Now: `shutdown(wait=False, cancel_futures=True)` so the queued
    futures are cancelled and the executor refuses new work, then
    bounded-poll on whether the worker threads exited within
    `timeout`. If they didn't, log at WARN — the daemon threads
    will be killed at interpreter exit, but at least we don't hang
    the caller. The honest contract: `shutdown_executor` ALWAYS
    returns within ~`timeout` seconds.

    Note: ThreadPoolExecutor stores worker thread refs in `_threads`
    (a set). We poll there for liveness; if any thread is non-daemon
    (the default!) the interpreter will still wait for it at exit,
    which is a separate-but-related bug — log it explicitly so it's
    visible.
    """
    if executor is None:
        return

    is_process_pool = hasattr(executor, "_processes")

    if is_process_pool:
        current = getattr(executor, "_processes", None) or {}
        processes_snapshot = list(current.values())

        try:
            executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass

        deadline_split = max(timeout / 2.0, 0.1)
        for proc in processes_snapshot:
            if proc is None or not proc.is_alive():
                continue
            try:
                proc.join(timeout=deadline_split)
                if proc.is_alive():
                    proc.terminate()
                    proc.join(timeout=deadline_split)
                if proc.is_alive():
                    proc.kill()
                    proc.join(timeout=0.5)
            except Exception:  # pragma: no cover — defensive
                pass

        try:
            executor.shutdown(wait=True, cancel_futures=True)
        except Exception:  # pragma: no cover — defensive
            pass
        return

    # ThreadPool path.
    threads_snapshot = list(getattr(executor, "_threads", set()) or [])
    try:
        executor.shutdown(wait=False, cancel_futures=True)
    except Exception:
        pass

    if not threads_snapshot:
        return

    import time as _time
    deadline = _time.monotonic() + timeout
    for thread in threads_snapshot:
        remaining = deadline - _time.monotonic()
        if remaining <= 0:
            break
        try:
            thread.join(timeout=remaining)
        except Exception:  # pragma: no cover — defensive
            pass

    still_alive = [t for t in threads_snapshot if t.is_alive()]
    if still_alive:
        non_daemon = [t for t in still_alive if not t.daemon]
        # Log via stderr write to stay safe even if logging itself is
        # in a wedged state (this helper is reachable from atexit).
        import sys as _sys
        try:
            _sys.stderr.write(
                f"[threadhygiene] shutdown_executor: {len(still_alive)} "
                f"thread(s) for {name!r} did not exit within {timeout}s "
                f"(non_daemon={len(non_daemon)}). Threads cannot be killed; "
                f"daemon threads will die at interpreter exit, non-daemons "
                f"will block exit indefinitely.\n"
            )
            _sys.stderr.flush()
        except Exception:  # pragma: no cover — defensive
            pass


__all__ = ["StopSignal", "join_or_raise", "shutdown_executor"]
