"""Out-of-process watchdog for `photonic_synesthesia`.

**This package MUST remain stdlib-only.** It runs in a separate process
(`multiprocessing.Process(..., start_method='spawn')`) whose job is to
detect main-process stalls and escalate to hard-kill when the
main process is wedged in a GIL-holding C extension.

Rules:
  1. No imports from `photonic_synesthesia.*` anywhere in this package.
     The `spawn` start method re-executes this module's imports; pulling
     in librosa/numpy/madmom would add 1-3 s to watchdog startup AND
     reintroduce the problem — a watchdog that itself holds the GIL
     while importing cannot monitor anything.
  2. Only stdlib (`struct`, `os`, `signal`, `time`, `sys`, `fcntl`,
     `multiprocessing.shared_memory`, `threading`, `atexit`) and
     whatever ships with CPython.
  3. A CI test greps this package for any `photonic_synesthesia` import
     and fails the build if found.

Cycle-5 panel LS3 (4/4 reviewers agreed the cycle-1 SIGUSR1-primary
design was flawed). Cycle-2 plan:
  - Watchdog DETECTS stalls out-of-process → guaranteed GIL-immune.
  - Watchdog ACTUATES via SIGKILL as primary fail-safe (interrupts
    even C extensions holding the GIL). SIGUSR1 is best-effort for
    soft stalls. `blackout_requested` shmem flag is a secondary
    trigger for `_emergency_loop` in main.
  - Hardware fail-safe (Ether Dream DAC data-starvation blank) is
    the final line of defense once SIGKILL terminates main's
    frame-streaming.
"""

from photonic_watchdog.shmem import WatchdogSharedState

__all__ = ["WatchdogSharedState"]
