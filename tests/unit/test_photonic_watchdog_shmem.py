"""Seqlock + shared-memory invariants for the out-of-process watchdog.

Cycle-5 panel LS3: covers the shared-memory protocol between main and
watchdog without spawning a real subprocess. Runs in the parent process
only; spawn-based stall tests live in `test_photonic_watchdog_stall.py`.
"""

from __future__ import annotations

import os

import pytest

from photonic_watchdog.shmem import StaleRead, WatchdogSharedState


@pytest.fixture
def fresh_shmem() -> WatchdogSharedState:
    """Creator-side shared segment. Always cleans up after the test so
    `/dev/shm/photonic_watchdog_state_v1` isn't left behind."""
    state = WatchdogSharedState(create=True)
    try:
        yield state
    finally:
        try:
            state.close()
            state.unlink()
        except Exception:
            pass


def test_fresh_segment_reads_zeros(fresh_shmem: WatchdogSharedState) -> None:
    snapshot = fresh_shmem.read()
    assert snapshot.seq == 0  # even = stable
    assert snapshot.main_heartbeat == 0
    assert snapshot.watchdog_heartbeat == 0
    assert snapshot.blackout_requested == 0


def test_write_main_round_trips(fresh_shmem: WatchdogSharedState) -> None:
    fresh_shmem.write_main(
        main_heartbeat=17,
        tick_number=17,
        dmx_frames_sent=42,
        ilda_frames_sent=7,
    )
    snap = fresh_shmem.read()
    assert snap.main_heartbeat == 17
    assert snap.tick_number == 17
    assert snap.dmx_frames_sent == 42
    assert snap.ilda_frames_sent == 7
    # Watchdog fields untouched
    assert snap.watchdog_heartbeat == 0
    assert snap.blackout_requested == 0


def test_write_watchdog_does_not_touch_main_fields(
    fresh_shmem: WatchdogSharedState,
) -> None:
    fresh_shmem.write_main(main_heartbeat=100, tick_number=100)
    fresh_shmem.write_watchdog(
        watchdog_heartbeat=5, watchdog_pid=os.getpid(), blackout_requested=1
    )
    snap = fresh_shmem.read()
    assert snap.main_heartbeat == 100
    assert snap.tick_number == 100
    assert snap.watchdog_heartbeat == 5
    assert snap.watchdog_pid == os.getpid()
    assert snap.blackout_requested == 1


def test_seqlock_counter_is_even_after_writer_finishes(
    fresh_shmem: WatchdogSharedState,
) -> None:
    """After a complete write, seq is even (no torn state observable)."""
    for _ in range(10):
        fresh_shmem.write_main(main_heartbeat=1)
        snap = fresh_shmem.read()
        assert snap.seq % 2 == 0, "seqlock must return to even after write"


def test_partial_write_seq_odd_triggers_retry_then_stale(
    fresh_shmem: WatchdogSharedState,
) -> None:
    """If seq is left odd (simulating a writer that crashed mid-update),
    reads spin until MAX_READ_RETRIES and then raise StaleRead."""
    # Force seq to an odd value by directly writing into the segment.
    fresh_shmem._write_seq(1)
    with pytest.raises(StaleRead):
        fresh_shmem.read()


def test_cleanup_stale_segment_before_create() -> None:
    """A stale segment from a prior crash MUST NOT block a fresh create."""
    leaked = WatchdogSharedState(create=True)
    leaked.close()  # deliberately DO NOT unlink — simulate crash
    try:
        # New "startup" should succeed despite the leftover segment.
        fresh = WatchdogSharedState(create=True)
        try:
            snap = fresh.read()
            assert snap.seq == 0  # re-zeroed
        finally:
            fresh.close()
            fresh.unlink()
    finally:
        # Belt + braces cleanup.
        try:
            leaked.unlink()
        except Exception:
            pass


def test_attacher_can_read_creators_writes(
    fresh_shmem: WatchdogSharedState,
) -> None:
    """Simulates the main↔watchdog attach pattern. Attacher must see
    the creator's writes without creating its own segment."""
    fresh_shmem.write_main(main_heartbeat=99, tick_number=99)
    attached = WatchdogSharedState(create=False)
    try:
        snap = attached.read()
        assert snap.main_heartbeat == 99
        assert snap.tick_number == 99
    finally:
        attached.close()


def test_write_preserves_fields_not_passed(
    fresh_shmem: WatchdogSharedState,
) -> None:
    """Caller passes only changed fields; others must be preserved."""
    fresh_shmem.write_main(main_heartbeat=1, tick_number=1)
    fresh_shmem.write_main(dmx_frames_sent=50)  # only dmx
    snap = fresh_shmem.read()
    assert snap.main_heartbeat == 1  # preserved
    assert snap.tick_number == 1  # preserved
    assert snap.dmx_frames_sent == 50  # updated
