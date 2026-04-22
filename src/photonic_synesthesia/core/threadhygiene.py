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
import concurrent.futures.thread as _threadpool_impl
import sys
import threading
import weakref
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


class DaemonThreadPoolExecutor(concurrent.futures.ThreadPoolExecutor):
    """ThreadPoolExecutor variant whose worker threads are daemonized.

    This is for long-lived process-singleton pools where the honest
    shutdown contract is "best effort, bounded wait." A wedged worker
    must not pin interpreter exit forever once the caller has already
    accepted that the work cannot be recovered in-process.

    Implementation note: CPython keeps changing the private worker
    bootstrap shape across minor versions. 3.12 uses
    `_worker(executor_ref, work_queue, initializer, initargs)`;
    early 3.13 builds added a separate `ctx` parameter; 3.14 folds the
    initializer into the context and no longer stores `_initializer` /
    `_initargs` on the executor instance. Branch on the runtime's
    actual private attributes instead of a fixed version tuple so the
    daemonized override matches the stdlib executor layout in use.
    """

    def _adjust_thread_count(self) -> None:
        if self._idle_semaphore.acquire(timeout=0):
            return

        def weakref_cb(_, q=self._work_queue):
            q.put(None)

        num_threads = len(self._threads)
        if num_threads >= self._max_workers:
            return

        thread_name = "%s_%d" % (self._thread_name_prefix or self, num_threads)

        if hasattr(self, "_create_worker_context") and hasattr(self, "_initializer"):
            # 3.13 transitional layout: context object plus explicit
            # initializer/initargs still live on the executor instance.
            worker_args = (
                weakref.ref(self, weakref_cb),
                self._create_worker_context(),
                self._work_queue,
                self._initializer,
                self._initargs,
            )
        elif hasattr(self, "_create_worker_context"):
            # 3.14+: initializer/initargs are folded into the worker
            # context returned by `_create_worker_context()`.
            worker_args = (
                weakref.ref(self, weakref_cb),
                self._create_worker_context(),
                self._work_queue,
            )
        else:
            # 3.12 signature: (executor_ref, work_queue, initializer, initargs).
            worker_args = (
                weakref.ref(self, weakref_cb),
                self._work_queue,
                self._initializer,
                self._initargs,
            )

        worker = threading.Thread(
            name=thread_name,
            target=_threadpool_impl._worker,
            args=worker_args,
            daemon=True,
        )
        worker.start()
        self._threads.add(worker)
        _threadpool_impl._threads_queues[worker] = self._work_queue


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
        daemon = [t for t in still_alive if t.daemon]
        if daemon:
            try:
                for thread in daemon:
                    _threadpool_impl._threads_queues.pop(thread, None)
            except Exception:
                pass
        # Log via stderr write to stay safe even if logging itself is
        # in a wedged state (this helper is reachable from atexit).
        import sys as _sys
        try:
            _sys.stderr.write(
                f"[threadhygiene] shutdown_executor: {len(still_alive)} "
                f"thread(s) for {name!r} did not exit within {timeout}s "
                f"(daemon={len(daemon)}, non_daemon={len(non_daemon)}). "
                f"Threads cannot be killed; daemon workers are detached "
                f"from concurrent.futures atexit joins, non-daemons will "
                f"still block exit indefinitely.\n"
            )
            _sys.stderr.flush()
        except Exception:  # pragma: no cover — defensive
            pass


__all__ = [
    "DaemonThreadPoolExecutor",
    "StopSignal",
    "join_or_raise",
    "shutdown_executor",
]
