"""Stall-detection + escalation ladder for the out-of-process watchdog.

Cycle-5 panel LS3: the watchdog's whole job is to notice when the main
graph's heartbeat stops advancing and to take progressively harder
actions. These tests cover all three escalation steps without spinning
up real subprocesses (which would bloat the test suite by several
seconds per run):

  1. Heartbeat advancing → no escalation.
  2. Heartbeat static past MAX_SOFT_STALL_MS → `blackout_requested=1`
     + SIGUSR1 sent to main_pid.
  3. Heartbeat static past MAX_HARD_STALL_MS → SIGKILL sent.

Approach: monkeypatch `signal.signal` (since the watchdog loop uses
`signal.signal` which only works from the main thread) and `os.kill`
(so we can observe signal escalation without actually killing anything),
then run `watchdog_loop` in a background thread with aggressively short
thresholds so the test completes in <200 ms.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from photonic_watchdog import loop as watchdog_loop_module
from photonic_watchdog.loop import watchdog_loop
from photonic_watchdog.shmem import WatchdogSharedState


@pytest.fixture
def shmem() -> WatchdogSharedState:
    state = WatchdogSharedState(create=True)
    try:
        yield state
    finally:
        try:
            state.close()
            state.unlink()
        except Exception:
            pass


@pytest.fixture
def kill_recorder(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, int]]:
    """Replace os.kill with a recorder. Watchdog needs os.kill for the
    escalation ladder; the test asserts on the recorded calls rather
    than requiring real processes."""
    recorded: list[tuple[int, int]] = []

    def _fake_kill(pid: int, sig: int) -> None:
        recorded.append((pid, sig))

    monkeypatch.setattr(watchdog_loop_module.os, "kill", _fake_kill)
    return recorded


@pytest.fixture
def noop_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Watchdog loop calls `signal.signal(SIGTERM, handler)`, which
    raises ValueError from a background thread. Tests run the loop in
    a thread, so replace signal.signal with a no-op for the duration."""
    monkeypatch.setattr(
        watchdog_loop_module.signal, "signal", lambda *args, **kwargs: None
    )


@pytest.fixture
def short_thresholds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop escalation thresholds so the full ladder completes in
    ~200 ms."""
    monkeypatch.setattr(watchdog_loop_module, "MAX_SOFT_STALL_MS", 50)
    monkeypatch.setattr(watchdog_loop_module, "MAX_HARD_STALL_MS", 150)
    monkeypatch.setattr(watchdog_loop_module, "WATCHDOG_TICK_SECONDS", 0.01)


def _run_loop_in_thread(main_pid: int) -> threading.Thread:
    """Spawn the watchdog loop in a background thread. Returns once the
    loop exits (after SIGKILL escalation or shmem close)."""
    thread = threading.Thread(
        target=watchdog_loop, args=(main_pid,), daemon=True
    )
    thread.start()
    return thread


def _wait_until(predicate, timeout_s: float = 1.0, tick: float = 0.005) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(tick)
    return False


def test_advancing_heartbeat_prevents_escalation(
    shmem: WatchdogSharedState,
    kill_recorder: list[tuple[int, int]],
    noop_signal: None,
    short_thresholds: None,
) -> None:
    """Happy path: if main keeps advancing its heartbeat, the watchdog
    must never escalate."""
    main_pid = 99999  # fake — kill is recorded not delivered

    # Seed heartbeat so watchdog's `last_main_hb = -1` starts resetting.
    shmem.write_main(main_heartbeat=1)

    thread = _run_loop_in_thread(main_pid)

    # Advance heartbeat faster than MAX_SOFT_STALL_MS for ~300 ms.
    deadline = time.monotonic() + 0.3
    hb = 1
    while time.monotonic() < deadline:
        hb += 1
        shmem.write_main(main_heartbeat=hb)
        time.sleep(0.015)  # well under 50ms soft threshold

    snap = shmem.read()
    assert snap.blackout_requested == 0, (
        "advancing heartbeat should never trigger blackout_requested"
    )
    assert not kill_recorder, (
        f"advancing heartbeat should never trigger os.kill; got {kill_recorder}"
    )

    # Drain the thread: stop heartbeating and wait for the hard-stall
    # path to exit the loop (~150 ms threshold + 1 loop-tick). Joining
    # here prevents the daemon thread from piling up across the suite.
    thread.join(timeout=0.5)
    assert not thread.is_alive(), "watchdog thread must exit after hard stall"


def test_soft_stall_sets_blackout_and_sends_sigusr1(
    shmem: WatchdogSharedState,
    kill_recorder: list[tuple[int, int]],
    noop_signal: None,
    short_thresholds: None,
) -> None:
    """Heartbeat static past MAX_SOFT_STALL_MS must set
    `blackout_requested=1` AND send SIGUSR1."""
    import signal as _signal

    main_pid = 99999
    shmem.write_main(main_heartbeat=7)  # seed, then never update again

    thread = _run_loop_in_thread(main_pid)

    # Soft threshold is 50ms; allow ~200ms for the loop to notice +
    # escalate. Do NOT wait past 150ms hard threshold or we'd also
    # see SIGKILL (tested separately).
    escalated = _wait_until(
        lambda: shmem.read().blackout_requested == 1, timeout_s=0.14
    )
    assert escalated, "watchdog must raise blackout_requested on soft stall"

    # Check that SIGUSR1 was among the delivered signals.
    sigusr1_calls = [call for call in kill_recorder if call[1] == _signal.SIGUSR1]
    assert sigusr1_calls, (
        f"watchdog must send SIGUSR1 on soft escalation; got {kill_recorder}"
    )
    assert sigusr1_calls[0][0] == main_pid

    # Let the loop run to hard-stall → SIGKILL exit, then join.
    thread.join(timeout=0.5)
    assert not thread.is_alive(), "watchdog thread must exit after hard stall"


def test_hard_stall_sends_sigkill(
    shmem: WatchdogSharedState,
    kill_recorder: list[tuple[int, int]],
    noop_signal: None,
    short_thresholds: None,
) -> None:
    """Heartbeat static past MAX_HARD_STALL_MS must send SIGKILL. This
    is the watchdog's terminal action — main is gone, DAC sees data
    starvation, hardware fails safe."""
    import signal as _signal

    main_pid = 99999
    shmem.write_main(main_heartbeat=1)

    thread = _run_loop_in_thread(main_pid)

    killed = _wait_until(
        lambda: any(call[1] == _signal.SIGKILL for call in kill_recorder),
        timeout_s=0.5,
    )
    assert killed, (
        f"watchdog must send SIGKILL on hard escalation; got {kill_recorder}"
    )

    sigkill_calls = [c for c in kill_recorder if c[1] == _signal.SIGKILL]
    assert sigkill_calls[0][0] == main_pid

    # Escalation order: SIGUSR1 before SIGKILL.
    sigusr1_calls = [c for c in kill_recorder if c[1] == _signal.SIGUSR1]
    assert sigusr1_calls, "soft escalation must precede hard"
    assert kill_recorder.index(sigusr1_calls[0]) < kill_recorder.index(
        sigkill_calls[0]
    ), "SIGUSR1 must be sent BEFORE SIGKILL"

    # After SIGKILL the loop exits.
    thread.join(timeout=0.5)
    assert not thread.is_alive(), "watchdog must exit after SIGKILL"


def test_ilda_emergency_loop_arms_on_shmem_blackout_flag(
    shmem: WatchdogSharedState,
) -> None:
    """Cycle-5 panel LS3 (Kilo F4): the ILDA emergency thread now polls
    `blackout_requested`. A rising edge on the flag must arm the
    emergency-until window so blank frames are streamed even if SIGUSR1
    delivery is delayed."""
    from photonic_synesthesia.core.config import (
        ILDAConfig,
        LaserSafetyConfig,
    )
    from photonic_synesthesia.graph.nodes.ilda_output import ILDADACOutputNode

    config = ILDAConfig()
    safety = LaserSafetyConfig()
    node = ILDADACOutputNode(config=config, safety=safety, fixtures=[])
    node.attach_watchdog_shmem(shmem)

    # Simulate `start()` state manually — don't actually start the thread
    # because that would open a real Ether Dream client. Instead, exercise
    # _emergency_loop's one-shot observation logic by calling it with
    # time bounded via the _thread_stop Event.
    #
    # Simpler: directly drive the flag-rising-edge logic by invoking the
    # loop for one iteration. We check the assertion on _emergency_until.
    assert node._emergency_until == 0.0

    shmem.write_watchdog(blackout_requested=1)
    node._running = True
    # Arrange for the loop to exit after one iteration.
    stop_thread = threading.Thread(
        target=lambda: (time.sleep(0.1), node._thread_stop.set()), daemon=True
    )
    stop_thread.start()
    node._emergency_loop()

    # The rising-edge must have armed the hold.
    assert node._emergency_until > 0.0, (
        "rising edge on shmem blackout_requested must arm _emergency_until"
    )


def test_ilda_emergency_loop_tolerates_shmem_read_errors(
    shmem: WatchdogSharedState,
) -> None:
    """If the shmem segment is yanked mid-run (main crashed + unlinked),
    the emergency loop MUST keep running — it is the last in-process
    line of defense."""
    from photonic_synesthesia.core.config import (
        ILDAConfig,
        LaserSafetyConfig,
    )
    from photonic_synesthesia.graph.nodes.ilda_output import ILDADACOutputNode

    node = ILDADACOutputNode(
        config=ILDAConfig(), safety=LaserSafetyConfig(), fixtures=[]
    )

    class _BrokenShmem:
        def read(self) -> Any:
            raise RuntimeError("segment disappeared")

    node.attach_watchdog_shmem(_BrokenShmem())
    node._running = True

    stop_thread = threading.Thread(
        target=lambda: (time.sleep(0.05), node._thread_stop.set()), daemon=True
    )
    stop_thread.start()

    # Should NOT raise — broken shmem is swallowed.
    node._emergency_loop()


# ---------------------------------------------------------------------------
# D2: consecutive StaleRead diagnostic
# ---------------------------------------------------------------------------


def test_consecutive_stale_reads_emit_diagnostic(
    kill_recorder: list[tuple[int, int]],
    noop_signal: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D2 invariant: when the shmem keeps raising StaleRead (simulates
    a crashed writer that left seq stuck odd), the watchdog emits a
    one-shot diagnostic at the configured threshold — not silently
    tick forever."""
    from photonic_watchdog.shmem import StaleRead, WatchdogState

    shmem = WatchdogSharedState(create=True)
    diagnostics: list[str] = []
    # Two-phase fake `read`: raise StaleRead enough times to trigger
    # the diagnostic, then return a stable snapshot so the loop's
    # normal stall detection can fire SIGKILL and exit. Without this,
    # the loop would spin forever (StaleRead → continue) and the
    # leaked thread would trip the cycle-6 E2 leak canary.
    stale_count = {"n": 0}
    STALES_BEFORE_RECOVERY = 30  # > STALE_WARN_THRESHOLD (20)

    def _phased_read() -> WatchdogState:
        stale_count["n"] += 1
        if stale_count["n"] <= STALES_BEFORE_RECOVERY:
            raise StaleRead("synthetic stale for test")
        # After the diagnostic has fired, return a snapshot whose
        # main_heartbeat never changes — the loop interprets this as
        # a hard stall and SIGKILLs (recorded by kill_recorder).
        return WatchdogState(
            seq=0, main_heartbeat=1, tick_number=1,
            dmx_frames_sent=0, ilda_frames_sent=0,
            watchdog_heartbeat=0, watchdog_pid=0,
            blackout_requested=0, emergency_stop=0,
        )

    thread = None
    try:
        monkeypatch.setattr(
            watchdog_loop_module,
            "_write_diagnostic",
            lambda msg: diagnostics.append(msg),
        )
        monkeypatch.setattr(shmem, "read", _phased_read)

        # Keep thresholds aggressive so the diagnostic fires AND the
        # SIGKILL escalation lets the loop exit cleanly within the test.
        monkeypatch.setattr(watchdog_loop_module, "MAX_SOFT_STALL_MS", 50)
        monkeypatch.setattr(watchdog_loop_module, "MAX_HARD_STALL_MS", 200)
        monkeypatch.setattr(watchdog_loop_module, "WATCHDOG_TICK_SECONDS", 0.005)
        monkeypatch.setattr(
            watchdog_loop_module, "WatchdogSharedState", lambda create: shmem
        )

        thread = _run_loop_in_thread(99999)

        # 20 consecutive stales × 5ms tick = 100 ms.
        assert _wait_until(
            lambda: any("stale_read_streak" in d for d in diagnostics),
            timeout_s=2.0,
        ), f"stale-read diagnostic never emitted; saw: {diagnostics}"

        # SIGKILL escalation lets the loop exit; canary requires a
        # joined thread.
        assert _wait_until(lambda: not thread.is_alive(), timeout_s=2.0), (
            "watchdog loop never exited — leak canary will fail"
        )
    finally:
        try:
            shmem.close()
            shmem.unlink()
        except Exception:
            pass
        if thread is not None:
            thread.join(timeout=1.0)
