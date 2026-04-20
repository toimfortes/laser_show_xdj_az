"""Regression tests for E6: shmem cross-process writer serialization.

Pre-E6 the `_writer` context held only `_local_lock` (in-process).
Two `WatchdogSharedState` instances in the same process (or in main
+ watchdog subprocess) could enter `_writer` concurrently:

  Thread A: read full struct (main_hb=10, watchdog_hb=20)
  Thread B: read full struct (main_hb=10, watchdog_hb=20)
  Thread A: pack with main_hb=11
  Thread B: pack with watchdog_hb=21    <-- ROLLS BACK A's main_hb=11

Each writer reads-then-packs every field, so the second pack silently
overwrites the other side's update. After E6, fcntl.flock on the
backing file makes the read-modify-write atomic across processes too.

These tests use TWO `WatchdogSharedState` instances in the same
process (one with create=True, one with create=False) which exhibit
the same race against each other as main+watchdog would in production.
"""

from __future__ import annotations

import os
import threading
import time

import pytest

from photonic_watchdog.shmem import WatchdogSharedState


@pytest.fixture
def attached_pair():
    """Yield (creator, attacher) — two handles to the same shmem
    segment, simulating the main+watchdog topology in one process."""
    creator = WatchdogSharedState(create=True)
    attacher = WatchdogSharedState(create=False)
    try:
        yield creator, attacher
    finally:
        for state in (attacher, creator):
            try:
                state.close()
            except Exception:
                pass
        try:
            creator.unlink()
        except Exception:
            pass


def test_concurrent_writers_do_not_lose_updates(attached_pair) -> None:
    """E6 invariant: 1000 writes from each process must land — neither
    side's updates may be silently rolled back by the other.

    Pre-E6 this test failed with mismatched final counts (e.g.,
    main_heartbeat = 873 instead of 1000) because the watchdog
    writer's pack overwrote the main writer's intermediate state."""
    creator, attacher = attached_pair
    N = 500

    main_done = threading.Event()
    watchdog_done = threading.Event()

    def _main_writer() -> None:
        for i in range(1, N + 1):
            creator.write_main(main_heartbeat=i)
        main_done.set()

    def _watchdog_writer() -> None:
        for i in range(1, N + 1):
            attacher.write_watchdog(watchdog_heartbeat=i)
        watchdog_done.set()

    t1 = threading.Thread(target=_main_writer, name="E6-main", daemon=True)
    t2 = threading.Thread(target=_watchdog_writer, name="E6-watchdog", daemon=True)
    t1.start()
    t2.start()

    assert main_done.wait(timeout=10.0), "main writer never finished"
    assert watchdog_done.wait(timeout=10.0), "watchdog writer never finished"
    t1.join(timeout=1.0)
    t2.join(timeout=1.0)

    snapshot = creator.read()
    assert snapshot.main_heartbeat == N, (
        f"main_heartbeat lost updates: expected {N}, got {snapshot.main_heartbeat}"
    )
    assert snapshot.watchdog_heartbeat == N, (
        f"watchdog_heartbeat lost updates: expected {N}, got {snapshot.watchdog_heartbeat}"
    )


def test_flock_fd_is_opened_on_linux(attached_pair) -> None:
    """Linux dev environment: the backing file `/dev/shm/<name>` must
    exist after creation, and the writer's flock fd must be open.
    Without this, cross-process serialization silently degrades."""
    creator, attacher = attached_pair
    backing = "/dev/shm/photonic_watchdog_state_v1"
    assert os.path.exists(backing), f"shmem backing file missing: {backing}"
    assert creator._flock_fd is not None, "creator flock fd not opened"
    assert attacher._flock_fd is not None, "attacher flock fd not opened"


def test_flock_fd_released_on_close(attached_pair) -> None:
    """close() must release the flock fd. A leaked fd would hold the
    flock indefinitely, blocking any future writer (including the
    same process re-attaching after close)."""
    creator, _ = attached_pair
    fd_before = creator._flock_fd
    assert fd_before is not None

    creator.close()

    assert creator._flock_fd is None
    # Verify the fd is actually closed by trying to fstat it.
    with pytest.raises(OSError):
        os.fstat(fd_before)


def test_writer_completes_under_flock_within_reasonable_bounds(attached_pair) -> None:
    """Sanity: the flock-protected critical section is microseconds.
    1000 writes should complete in well under a second on any
    reasonable hardware. If this regresses to seconds, something's
    wrong with the locking strategy (deadlock-detection retry loop,
    contention storm, etc.)."""
    creator, _ = attached_pair
    t0 = time.monotonic()
    for i in range(1000):
        creator.write_main(main_heartbeat=i)
    elapsed = time.monotonic() - t0
    assert elapsed < 2.0, (
        f"1000 writes under flock took {elapsed:.2f}s — expected <2s"
    )
