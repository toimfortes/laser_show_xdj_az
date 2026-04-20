"""Watchdog process entry point.

Runs in its own `multiprocessing.Process(start_method='spawn')`. The
spawn method re-executes THIS module's imports in the child — which
is why this module imports ONLY stdlib. Pulling in
`photonic_synesthesia.*` (and thus librosa + numpy + madmom) would
inflate watchdog startup from ~150 ms to 2-4 s AND reintroduce the
GIL-hold scenario we're trying to monitor.

Stall detection + escalation ladder:

  1. Main heartbeat static for MAX_SOFT_STALL_MS (default 1000)
     → write `blackout_requested=1` to shmem. `_emergency_loop` in
       main polls this and starts streaming blank frames (works
       for soft stalls where main is still running Python).
     → Send `SIGUSR1` to main (best-effort — handler runs when
       main's interpreter next checks for pending signals).
  2. Main heartbeat STILL static after MAX_HARD_STALL_MS (default 3000)
     → `SIGKILL` the main process. Interrupts even GIL-holding C
       extensions. The Ether Dream DAC sees the TCP drop + data
       starvation and fails safe per its documented behavior.
     → Watchdog exits (main is gone; nothing to watch).

This file does NOT import `photonic_synesthesia.*`. A CI test
(`test_watchdog_import_discipline`) verifies that via AST parse.
"""

from __future__ import annotations

import os
import signal
import sys
import time
from typing import Any

from photonic_watchdog.shmem import StaleRead, WatchdogSharedState


# Stall thresholds. Expose as module-level so callers can monkeypatch
# for tests without recompiling.
MAX_SOFT_STALL_MS = 1000  # after this much silence, request soft blackout
MAX_HARD_STALL_MS = 3000  # after this much silence, SIGKILL main

# Watchdog tick: how often we check main's heartbeat. 50 ms = 20 Hz
# well under the 1 s soft-stall threshold, giving us ~20 samples
# before escalation. Trade-off: shorter tick = faster detection but
# more CPU; 50 ms is a good balance.
WATCHDOG_TICK_SECONDS = 0.05


def _write_diagnostic(message: str) -> None:
    """Watchdog diagnostic output.

    Uses `sys.stderr.write` with plain strings — NOT `logger` — to
    avoid pulling in `structlog` which would chain into
    `photonic_synesthesia.core.logging`. Keeps the import graph
    stdlib-clean.
    """
    try:
        sys.stderr.write(f"[watchdog] {message}\n")
        sys.stderr.flush()
    except Exception:
        pass


def watchdog_loop(main_pid: int) -> None:
    """Entry point for the watchdog subprocess.

    Runs until main exits cleanly OR main is SIGKILL'd by the escalation
    ladder OR the watchdog itself receives SIGTERM/SIGINT.
    """
    # Attach to the shared memory segment main created.
    try:
        state = WatchdogSharedState(create=False)
    except FileNotFoundError:
        _write_diagnostic("shmem not found; main probably crashed before we started")
        return

    my_pid = os.getpid()
    state.write_watchdog(watchdog_pid=my_pid, watchdog_heartbeat=1)
    _write_diagnostic(f"started pid={my_pid} monitoring main_pid={main_pid}")

    last_main_hb = -1
    last_change_monotonic = time.monotonic()
    soft_escalated = False
    tick = 0

    # Set up clean-exit handlers (main's SIGTERM propagates here via
    # the parent-child relationship on typical shutdown).
    def _on_shutdown(signum: int, frame: Any) -> None:
        _write_diagnostic(f"received signal {signum}; exiting")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _on_shutdown)
    signal.signal(signal.SIGINT, _on_shutdown)

    try:
        while True:
            time.sleep(WATCHDOG_TICK_SECONDS)
            tick += 1

            # Heartbeat: advance our own counter so main can
            # unilateral-watch us (in case we crash).
            state.write_watchdog(watchdog_heartbeat=tick)

            # Check main's heartbeat.
            try:
                snapshot = state.read()
            except StaleRead:
                # Live-lock on seq — main may be stuck mid-write.
                # Treat as inconclusive this tick; keep watching.
                continue

            current_main_hb = snapshot.main_heartbeat

            if current_main_hb != last_main_hb:
                # Main advanced. Reset stall tracking.
                last_main_hb = current_main_hb
                last_change_monotonic = time.monotonic()
                soft_escalated = False
                # Also clear any stale blackout_requested (main recovered).
                if snapshot.blackout_requested:
                    state.write_watchdog(blackout_requested=0)
                continue

            # Main hasn't advanced. How long?
            silence_ms = (time.monotonic() - last_change_monotonic) * 1000.0

            # --- Soft stall escalation ---
            if silence_ms >= MAX_SOFT_STALL_MS and not soft_escalated:
                _write_diagnostic(
                    f"main stall detected ({silence_ms:.0f}ms silence); "
                    "requesting soft blackout + SIGUSR1"
                )
                state.write_watchdog(blackout_requested=1)
                # Best-effort SIGUSR1. If main is wedged in C ext, this
                # queues but doesn't fire until C returns. That's why
                # SIGKILL is the backstop.
                try:
                    os.kill(main_pid, signal.SIGUSR1)
                except ProcessLookupError:
                    _write_diagnostic(f"main_pid={main_pid} gone; exiting")
                    return
                except Exception as exc:
                    _write_diagnostic(f"SIGUSR1 failed: {exc}")
                soft_escalated = True

            # --- Hard stall escalation ---
            if silence_ms >= MAX_HARD_STALL_MS:
                _write_diagnostic(
                    f"main stall exceeded hard threshold ({silence_ms:.0f}ms); "
                    f"SIGKILL main_pid={main_pid} (DAC fails safe on data starvation)"
                )
                try:
                    os.kill(main_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except Exception as exc:
                    _write_diagnostic(f"SIGKILL failed: {exc}")
                _write_diagnostic("actuation complete; watchdog exiting")
                return

    finally:
        try:
            state.close()
        except Exception:
            pass
