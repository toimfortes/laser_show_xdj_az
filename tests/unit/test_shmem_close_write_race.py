"""Regression tests for shmem close/write race (cycle-6 B6).

Pre-B6, a graph tick firing after `close()` raised
`ValueError: operation forbidden on released memoryview` (or
occasionally segfaulted) because the writer touched `self._shm.buf`
without a closed check. B6 wraps close() under `_local_lock` so
writers either see `_closed=False` and complete OR see `_closed=True`
and no-op cleanly.
"""

from __future__ import annotations

import threading
import time

import pytest

from photonic_watchdog.shmem import StaleRead, WatchdogSharedState


@pytest.fixture
def shmem():
    state = WatchdogSharedState(create=True)
    yield state
    try:
        state.close()
    except Exception:
        pass
    try:
        state.unlink()
    except Exception:
        pass


def test_write_main_after_close_is_a_noop(shmem: WatchdogSharedState) -> None:
    """B6 invariant: a writer that arrives post-close must NOT access
    the released memoryview. It must silently return instead of
    raising ValueError or segfaulting."""
    shmem.close()
    # Must not raise — even though the shmem is closed.
    shmem.write_main(main_heartbeat=42)
    shmem.write_watchdog(blackout_requested=1)


def test_read_after_close_raises_stale_read(shmem: WatchdogSharedState) -> None:
    """Reads after close must raise StaleRead, not ValueError. Callers
    already handle StaleRead as "can't get a snapshot" — wedging a
    different exception type into the error path would crash the
    watchdog loop at shutdown."""
    shmem.close()
    with pytest.raises(StaleRead):
        shmem.read()


def test_concurrent_write_during_close_does_not_crash(shmem: WatchdogSharedState) -> None:
    """Stress test: spin a writer that never stops while we close.
    Pre-B6 this reliably raised `ValueError: operation forbidden on
    released memoryview` in the writer thread. Post-B6 the writer
    sees `_closed=True` on its next lock acquisition and returns."""
    stop = threading.Event()
    error: list[BaseException] = []

    def _writer_loop() -> None:
        counter = 0
        while not stop.is_set():
            counter += 1
            try:
                shmem.write_main(main_heartbeat=counter)
            except BaseException as exc:  # noqa: BLE001 - we want to see ANY crash
                error.append(exc)
                return

    worker = threading.Thread(target=_writer_loop, name="B6-writer", daemon=True)
    worker.start()
    # Let the writer spin for a bit so we're actually racing close().
    time.sleep(0.05)
    shmem.close()
    stop.set()
    worker.join(timeout=2.0)

    assert not worker.is_alive(), "writer must exit cleanly"
    assert not error, f"writer should never raise; got {error}"


def test_close_is_idempotent(shmem: WatchdogSharedState) -> None:
    """close() must be safe to call multiple times — the graph stop
    path and the atexit unlink both end up invoking it."""
    shmem.close()
    shmem.close()
    shmem.close()
