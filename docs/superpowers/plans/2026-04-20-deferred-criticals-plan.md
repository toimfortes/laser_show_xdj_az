# Plan: Close the Three Deferred CRITICAL Findings — Cycle 2

**Cycle-1 panel verdict:** 4/4 unanimous `PLAN_NEEDS_REVISION`.

This document is the cycle-2 revision. It absorbs every CRITICAL/HIGH finding from the four-reviewer panel (Codex / Gemini / Kilo / Claude) and materially redesigns the plan where the original architecture was unsound.

## Cycle-1 → Cycle-2 closure map

| # | Finding | Reviewers | Cycle-2 closure |
|---|---|---|---|
| 1 | **CRITICAL** — SIGUSR1 handler can't preempt GIL-held C extension. Central "GIL immunity" claim is effectively false. | 4/4 | **LS3 redesigned.** Primary fail-safe is now SIGKILL-on-stall, not SIGUSR1. Option (b) from the panel's suggestions. `_emergency_loop` thread explicitly retired or moved. SIGUSR1 downgraded to best-effort notification channel. |
| 2 | **CRITICAL** — LS2 Layer-2 back-translation assumes normalized coords; threshold is already int-space. | Claude | **LS2 redesigned.** Back-translation dropped. Protected-zone check uses the SAME `_point_is_protected` helper as `LaserZoneRuntimeNode` (factored into a shared module). Config-load invariant compares in identical units. |
| 3 | **CRITICAL** — SIGUSR1 emergency_blackout bypasses `laser_vector_interlock`. Regresses LS2's own invariant. | Claude | **LS3 redesigned.** No emergency path calls output-node methods directly anymore. The only blackout actuation that bypasses the interlock is SIGKILL (which stops all frame emission, hardware-safe via DAC data-starvation). |
| 4 | **HIGH** — A11's 40–80 ms premise is false. Codex benchmarked `_compute_authored_hash` at 0.942 ms. Real bottleneck was deepcopy (fixed in `c109ca0`). | 3/4 | **A11 downgraded to LOW.** Land benchmark test first, pin sub-5 ms assertion. If pin holds, no further action. If it fails, deepcopy-reduction is the target, not xxhash. |
| 5 | **HIGH** — Shared memory torn reads + `/dev/shm` leak on crash. | 3/4 | **LS3 schema redesigned.** Seqlock pattern for multi-byte fields; `atexit.register(unlink)`; stale-segment cleanup on startup; explicit `multiprocessing.Lock` for non-seqlock field groups. |
| 6 | **HIGH** — `time.sleep(3)` test validates wrong failure mode (sleep releases GIL). | 3/4 | **Test redesign.** Replace `time.sleep` with a pure-Python busy loop (`while t<deadline: pass`) and a numpy-large-array stall that mimics the librosa scenario. `@skipif(sys.platform == "win32")` for SIGUSR1 paths. |
| 7 | **HIGH** — Tactic 2 structural fingerprint breaks `_authored_cache` + stomp guard. | 3/4 | **Dropped from plan.** A11's premise was false; no reason to pursue lossy hashing. |
| 8 | **HIGH** — Tactic 3 captured-ref aliasing; `self.show_sections[:] = …` mutates in place. | 3/4 | **Dropped from plan.** Ibid. |
| 9 | **HIGH** — `_emergency_loop` thread (ilda_output.py:867) shares GIL vulnerability, never addressed. | Kilo | **LS3 redesigned.** `_emergency_loop` is EITHER retired (if watchdog does SIGKILL) OR the emergency-stream command is routed through shared memory so the watchdog process can drive it independently of main. Explicitly enumerated and fixed. |
| 10 | **HIGH** — `xxhash` has no pure-Python fallback (PyPI `xxhash` is a C extension). | Claude | **N/A now.** xxhash dropped; no dep change. |
| 11 | **MED** — `blackout_requested` shmem field is a dead write. | Kilo | **Removed.** Schema only contains fields that have consumers. |
| 12 | **MED** — `multiprocessing.Process` default `fork` with active daemon threads risks deadlock. | Kilo | **Explicit.** Plan now specifies `multiprocessing.get_context("spawn")` and documents why fork is unsafe with `SafetyMonitor` + `ILDA-Emergency-Output` threads present. |
| 13 | **MED** — `_last_point` contamination: if protected-zone blanks a point, next point's velocity anchors on the contaminated coord. | Kilo | **Addressed in LS2 implementation outline.** When the zone check blanks, reset `_last_point` to the last known SAFE coord. |
| 14 | **MED** — Velocity-scaling insertion ambiguity in LS2 Step 4. | Claude | **Explicit.** Plan now cites the exact insertion line (after `laser_vector_interlock.py:135`, before `ILDAPoint` construction at `:137`). |
| 15 | **MED** — Watchdog spawn cost ≫ 200 ms if it pulls `photonic_synesthesia.*`. | Claude | **Mandatory import discipline.** Watchdog module is top-level `photonic_watchdog/` outside the package, imports only stdlib. CI test greps for `photonic_synesthesia` imports in the watchdog and fails if found. |

---

## Plan: LS2 — Protected-zone gate, shared helper, `_last_point` discipline

### Problem (unchanged)

Pipeline today:

```
ilda_output → laser_zone_runtime → laser_vector_interlock → ilda_export → ilda_transport
```

`laser_zone_runtime` blanks points in the protected half-plane. `laser_vector_interlock` then clamps `x/y` to `[ilda_x_min, ilda_x_max] × [ilda_y_min, ilda_y_max]`. A mis-calibrated config (`ilda_y_max < protected_threshold`) can clamp a safe lit point DOWN into the protected zone.

### Cycle-2 fix (three layers)

**Layer 1 — shared protected-zone helper.** Factor the half-plane predicate out of `laser_zone_runtime` into `src/photonic_synesthesia/graph/safety/protected_zone.py`:

```python
# protected_zone.py — shared by laser_zone_runtime + laser_vector_interlock
from typing import Any

def is_point_protected(point: dict[str, Any], axis: str, threshold: float, below_is_protected: bool) -> bool:
    """The single source of truth for "is this ILDA point inside a
    crowd-protected half-plane?" Both callers read the threshold in the
    SAME coordinate space — the ILDA int-space ([-32767, 32767]) that
    `_clamp_coord(value * _ILDA_MAX)` produces. No unit translation."""
    value = float(point.get(axis, 0.0))
    return (value < threshold) if below_is_protected else (value > threshold)
```

Both nodes import this. No back-translation. Cycle-1's coordinate-space bug is structurally impossible.

**Layer 2 — config-load invariant.** In `_validate_startup_config` (cli.py), assert that for every laser fixture with a `safety_protected_half_plane`, the ILDA clamp bounds CANNOT push a safe point into the protected region:

```python
def _validate_laser_zone_config(fixtures, laser_safety):
    for fixture in fixtures:
        if fixture.type != "laser":
            continue
        hp = fixture.safety_protected_half_plane or {"axis": "y", "threshold": 0.0, "below_is_protected": True}
        axis, threshold, below_is_protected = hp["axis"], hp["threshold"], hp["below_is_protected"]
        # Threshold + clamp bounds MUST share the ILDA int-space (-32767..32767).
        # Literal-0.5 configs are always wrong in this space; catch them loudly.
        if not -32767 <= threshold <= 32767:
            raise ValueError(
                f"fixture {fixture.id!r}: protected_half_plane.threshold={threshold} "
                "out of ILDA int-space range [-32767, 32767]. Thresholds must be specified "
                "in the SAME coordinate space as ilda_{x,y}_{min,max} — likely you wrote "
                "a normalized (±1.0) value instead of the int-space equivalent."
            )
        if axis == "y":
            clamp_lo = laser_safety.ilda_y_min
            clamp_hi = laser_safety.ilda_y_max
        elif axis == "x":
            clamp_lo = laser_safety.ilda_x_min
            clamp_hi = laser_safety.ilda_x_max
        else:
            raise ValueError(f"fixture {fixture.id!r}: unknown protected axis {axis!r}")
        if below_is_protected:
            # protected region is value < threshold. Clamp must not push below threshold.
            if clamp_lo < threshold:
                raise ValueError(
                    f"fixture {fixture.id!r}: ilda_{axis}_min={clamp_lo} < "
                    f"protected_threshold={threshold}. A clamp would move a safe point "
                    "into the protected zone."
                )
        else:
            if clamp_hi > threshold:
                raise ValueError(...)
```

**Layer 3 — runtime backstop + `_last_point` discipline.** In `LaserVectorInterlockNode._interlock_frame`, AFTER the final `is_lit` decision (after line 135's blink-limiter) and BEFORE `ILDAPoint` construction (line 137):

```python
# Final geometric gate: protected-zone check AFTER all transformations.
# Lives AFTER clamps + velocity scaling + blink limiter; sees final (x, y).
from photonic_synesthesia.graph.safety.protected_zone import is_point_protected
hp = self._protected_half_plane_by_fixture.get(frame["fixture_id"])
if hp is not None:
    axis, threshold, below_is_protected = hp
    pseudo_point = {axis: y if axis == "y" else x}
    if is_point_protected(pseudo_point, axis, threshold, below_is_protected):
        # Force blank. Do NOT update _last_point with this contaminated coord;
        # keep the previous safe anchor so velocity calculations for subsequent
        # points don't cascade from an in-zone position.
        r = g = b = 0
        is_lit = False
        # Keep `last` pointing at the prior safe position (don't advance).
        # (Revert the line-148 update in the blanking case.)
```

### New tests

- `test_vector_interlock_blanks_clamped_point_in_protected_zone` — craft: `y=30` (safe, above threshold=0), `ilda_y_max=-50`; assert output is blanked.
- `test_vector_interlock_last_point_anchor_preserved_when_blanking_in_zone` — two consecutive ticks where the first is clamped into the zone and blanked; assert the second tick's velocity calculation uses the previous-safe position, not the zone coord.
- `test_startup_validation_rejects_ilda_bounds_overlapping_protected_zone` — invalid config, assert `_validate_startup_config` raises with a message that names both values.
- `test_startup_validation_rejects_normalized_threshold_in_int_space` — config with `threshold=0.5` (normalized), assert raises with the "you wrote a normalized value" hint.
- `test_zone_runtime_and_vector_interlock_share_one_predicate` — import `is_point_protected` in both nodes' test modules; mutation test: a stub predicate returning always-True in one of the two should blank EVERY point (confirms both nodes actually call the shared helper).

### Effort: ~3 hours. Risk: LOW (all mechanical, no concurrency).

---

## Plan: A11 — Benchmark first, act only if over budget

### Problem restatement (corrected)

Cycle-1's claim: `_compute_authored_hash` costs 40–80 ms under `_lock`, blocking the graph tick. **Panel falsified this.** Codex benchmarked at 0.942 ms on a real 5-min show (10 sections, 20 flags, 161 KB payload). Kilo identified the actual sources of stall:

1. `copy.deepcopy` on `_base_show_sections` + `show_sections` in `_replace_show_sections_locked` (runtime_context.py:354, 358). Each ~10–30 ms. **Already fixed in commit `c109ca0`** which reduced `update_show_section` from 6 deepcopies to 1.
2. Full-list deepcopies remain in `_replace_show_sections_locked` itself.

The cycle-1 xxhash plan solves the wrong problem with a wrong premise.

### Cycle-2 fix: measurement-first

**Phase 1 — benchmark and pin.**

```python
# tests/perf/test_compute_authored_hash_budget.py
def test_compute_authored_hash_under_5ms_for_realistic_show(benchmark_fixture_5min_show):
    ctx = PlaybackContext(...)
    ctx._replace_show_sections_locked(benchmark_fixture_5min_show)
    t0 = time.perf_counter()
    for _ in range(10):
        _compute_authored_hash(ctx.show_sections, ctx.timeline_flags, ctx.staged_look)
    median_ms = ((time.perf_counter() - t0) / 10) * 1000
    assert median_ms < 5.0, f"hash compute exceeded 5ms budget: {median_ms:.2f}ms"
```

If the benchmark passes (expected, per Codex's measurement), A11 is **CLOSED**. No code change needed.

**Phase 2 — only if benchmark fails.** If the pin fails, the REAL target is `_replace_show_sections_locked`'s own deepcopies:

```python
# Current (runtime_context.py:354, 358):
self._base_show_sections = copy.deepcopy(show_sections)
self.show_sections = copy.deepcopy(show_sections)
```

Fix: accept a pre-deepcopied `base_show_sections` from callers that already did one (like the cycle-5 `update_show_section` optimization), skip the double deepcopy. Only allocate a second list for `show_sections` (mutable for overlays).

**Phase 3 — Tactics 2 & 3 are DROPPED.** The panel confirmed both are unsound. No lossy fingerprints, no off-lock read-reacquire with aliased refs.

### Effort: ~1 hour (benchmark only; no code change expected). Risk: LOW.

---

## Plan: LS3 — SafetyMonitor as a separate process, SIGKILL as primary fail-safe

### Problem restatement

Panel agreed unanimously: separating the watchdog's DETECTION is fine and works. Separating the ACTUATION is the hard part. SIGUSR1 + Python signal handler can't preempt a GIL-held C extension. The cycle-1 plan leaned on SIGUSR1 as the primary actuation — that was wrong.

### Cycle-2 redesign: SIGKILL primary + hardware DAC-starvation fallback

Three actuation paths, ordered by reliability:

1. **SIGKILL on the main process** — the watchdog is POSIX-authoritative over main; `os.kill(main_pid, SIGKILL)` interrupts EVERYTHING, including C extensions holding the GIL. Process dies. The Ether Dream DAC sees the TCP connection drop + data starvation and fails safe (emergency stop per the device's documented behavior). This is the PRIMARY fail-safe.
2. **SIGUSR1 best-effort** — for soft stalls where main is doing CPU-bound Python work (pre-fix A11, still-running regen). SIGUSR1 eventually runs when main reaches a bytecode boundary, at which point a clean blackout happens with proper state. This is an OPTIMISTIC path — if it works, the show recovers; if it doesn't, SIGKILL wins.
3. **Watchdog's own blackout_requested shmem flag** — if main is running but SIGUSR1 is blocked (e.g., a Python signal mask during structlog serialization), `_emergency_loop` can poll the shmem flag as a secondary trigger. This closes Kilo's F4 (dead-write) finding AND gives `_emergency_loop` something useful to do during a soft stall before SIGKILL fires.

The "GIL immunity" claim is now **SCOPED**: detection is GIL-immune always; soft-actuation works for Python-level stalls; hard-stall fallback is SIGKILL + DAC hardware fail-safe, not "software blackout within N ms".

### Architecture

```
Main process:
  - PhotonicGraph + all nodes
  - Writes seqlock-protected shmem:
      seq (uint32), heartbeat_count (uint64), tick_number (uint64), emergency_stop (int32)
  - Registers SIGUSR1 handler: calls emergency_blackout() best-effort
  - `_emergency_loop` polls shmem[blackout_requested] every 20ms as secondary trigger

Watchdog process (multiprocessing.Process, start_method='spawn'):
  - Module lives at `photonic_watchdog/loop.py` OUTSIDE photonic_synesthesia.*
  - Imports ONLY stdlib: struct, os, signal, time, multiprocessing.shared_memory, fcntl
  - Event loop, 50ms tick
  - Reads shmem via seqlock; if main heartbeat static for MAX_SOFT_STALL_MS (default 1000):
      1. Writes blackout_requested=1 (may trigger `_emergency_loop` if main still runs)
      2. Sends SIGUSR1 (best-effort Python-level blackout)
      3. After MAX_HARD_STALL_MS (default 3000), sends SIGKILL to main_pid
      4. Writes its own audit log for post-mortem (watchdog_pid, stall_start_ts,
         actuation_reason, escalation_path)
  - Writes watchdog_heartbeat to shmem (for main's unilateral check during healthy operation)
  - On its own SIGTERM/SIGINT, cleanly unlink()s shmem
  - On photonic_watchdog/loop.py import, registers atexit to unlink
```

### Shared memory schema — seqlock-protected

```python
# photonic_watchdog/shmem.py — standalone module
import struct
from multiprocessing.shared_memory import SharedMemory

# Layout. All fields are aligned; seq brackets writer updates.
# Writer protocol:
#   seq += 1  (odd = "writer in progress")
#   pack_into(..., fields...)
#   seq += 1  (even = "consistent snapshot")
# Reader protocol:
#   loop:
#     seq1 = unpack(seq)
#     fields = unpack_from(offset=_FIELD_OFFSET)
#     seq2 = unpack(seq)
#     if seq1 == seq2 and seq1 % 2 == 0: return fields
#     (else retry; bounded retries prevent infinite loop if main is dead)

_LAYOUT = struct.Struct("=IQQqqIii")  # seq, heartbeat, tick, dmx_frames, ilda_frames, blackout, stop, wd_pid
_FIELDS = ("seq", "heartbeat", "tick", "dmx_frames", "ilda_frames", "blackout_requested", "emergency_stop", "watchdog_pid")
_SIZE = _LAYOUT.size

class WatchdogSharedState:
    """Seqlock-based shared memory between main and watchdog processes.

    WRITER ROLES (single-writer per field group):
      - Main:     heartbeat, tick, dmx_frames, ilda_frames, emergency_stop
      - Watchdog: blackout_requested, watchdog_pid
    BOTH use the same `seq` counter via separate write_main() / write_watchdog() calls,
    each acquiring a process-local `threading.Lock` + a `fcntl.flock` on the shmem file
    to serialize cross-process writes.

    READER (either): uses seqlock-retry to detect partial writes.

    Cleanup: `atexit.register(self.unlink)` on the creator side; on startup,
    attempt `SharedMemory(name=_NAME).unlink()` before `create=True` to clean
    up stale segments from a prior crash.
    """
    _NAME = "photonic_watchdog_state_v1"  # versioned for future migrations
    ...
```

### Import discipline (hard-enforced)

- `photonic_watchdog/` is a TOP-LEVEL directory, not inside `photonic_synesthesia/`.
- `photonic_watchdog/loop.py` imports ONLY `struct`, `os`, `signal`, `time`, `multiprocessing.shared_memory`, `fcntl`.
- No `logger = get_logger(...)` (that pulls structlog and the whole package). Use `sys.stderr.write` with plain strings for watchdog diagnostics.
- CI test: `test_watchdog_module_imports_only_stdlib` — `ast.parse` the watchdog module, walk `Import`/`ImportFrom`, assert nothing matches `photonic_synesthesia*`.
- Spawn cost target: < 150 ms. Measured in a startup benchmark.

### Handling `_emergency_loop`

Previously this thread ran in-process and was invisible to the plan. Cycle-2 decision: KEEP it, but give it a real job:

- Poll `shmem.blackout_requested` at its 20 ms tick (existing cadence) in addition to `_emergency_until`.
- If `blackout_requested=1`, stream blank frames for 500 ms (existing behavior), then clear the flag.
- Works when main is soft-stalled (Python-level) because the thread still gets GIL time. During hard C-ext stalls, it's blocked just like the signal handler — that's what SIGKILL is for.

### Tests

Replace cycle-1's `time.sleep(3)` tests with three distinct stall scenarios:

1. **Soft stall** (Python busy loop holds GIL):
   ```python
   def _pure_python_gil_hold(seconds: float):
       deadline = time.perf_counter() + seconds
       while time.perf_counter() < deadline:
           pass  # tight loop, holds GIL
   ```
   Assert: SIGUSR1 handler fires within ~1–2 s (after the loop), `_emergency_loop` streams blank frames during, blackout IS eventually observed.

2. **Hard C-extension stall** (simulate via `ctypes.CDLL` + a native function that sleeps without releasing GIL):
   Assert: main process is SIGKILL'd within MAX_HARD_STALL_MS + tolerance; shmem is unlinked; Ether Dream connection drops.

3. **Watchdog process death** (externally `os.kill(watchdog_pid, SIGKILL)` during healthy operation):
   Assert: main detects missing watchdog heartbeat within 2 s, triggers emergency_blackout locally, optionally re-spawns watchdog.

All three marked `@pytest.mark.slow` and `@pytest.mark.skipif(sys.platform == "win32")`. Windows path does NOT get SIGUSR1/SIGKILL coverage; explicitly documented.

### Effort estimate (updated): 8–12 hours

- photonic_watchdog package: 3 h
- WatchdogSharedState seqlock + cleanup: 2 h
- Main-process integration (shmem writes, signal handler, `_emergency_loop` polling): 2 h
- Tests (3 stall scenarios + import-discipline CI): 3 h
- Smoke-test with real Ether Dream + measured latency numbers: 2 h
- Documentation honesty pass (what's guaranteed, what's best-effort, what hardware you still need): 1 h

### Risk

- **POSIX-only.** Windows path is best-effort via `_emergency_loop` polling shmem; no SIGKILL, no SIGUSR1. Document explicitly.
- **DAC fail-safe behavior assumed.** The plan relies on Ether Dream failing safe on TCP drop. Verify against the actual DAC firmware before shipping to production.
- **Shared memory `/dev/shm`** — if the system runs out of shmem space, the watchdog fails to start. Document the memory requirement (< 1 KB; not a real concern).

---

## Honest disclosure (new section, cycle-2)

The cycle-1 plan implicitly claimed software could close the safety gap. The panel made clear this is false.

**What the cycle-2 plan delivers in software:**
- Detection of main-process stalls within ~1 s, regardless of GIL state.
- Soft-blackout within ~1–2 s for Python-level stalls (SIGUSR1 path).
- Hard-kill within ~3 s for C-extension stalls (SIGKILL + DAC data-starvation fail-safe).
- Protected-zone check as the last geometric gate before hardware (LS2 closed).
- Benchmark-backed confidence that the hot path runs under budget.

**What the cycle-2 plan does NOT deliver:**
- Sub-10 ms blackout latency (IEC 60825-1 requirement for scan-fail).
- Hardware shutter closure on failure (requires physical shutter; not software-addressable).
- Certified audience-scanning safety.

**For live audience-scanning shows**, pair this controller with:
- [Pangolin PASS](https://pangolin.com/products/pass) or equivalent hardware scan-fail safeguard.
- A physical E-stop mushroom wired to the laser enable interlock.
- Independent hardware MPE monitoring at the venue.

The software can be well-designed and honest about its limits, or poorly designed and lying about its limits. Cycle-1 was the latter; cycle-2 aims for the former.

---

## Sequencing + risk budget

| Task | Effort | Blocks | Risk |
|---|---|---|---|
| LS2 shared-helper + config invariant + runtime backstop + `_last_point` fix | 3 h | — | LOW (mechanical, no concurrency) |
| A11 benchmark pin | 1 h | — | LOW (measurement only; likely confirms "no action needed") |
| A11 deepcopy reduction in `_replace_show_sections_locked` (IF benchmark fails) | 2 h | A11 pin result | MED (touches the hot path; needs careful test) |
| LS3 watchdog process + seqlock shmem + SIGKILL path | 8–12 h | LS2 + A11 | HIGH (multiprocess + signal + hardware; needs real-DAC validation) |

**Total new code**: ~600 lines + ~400 lines of tests. Three PRs:

1. **LS2** (safest, lowest risk, ships first)
2. **A11 benchmark** (tiny, ships alongside LS2 or standalone)
3. **LS3** (biggest, ships last; requires bench-validated A11 to rule out hot-path interference)

---

## New archetype proposals

- **LS1b** — "Safety actuation path bypasses the geometric safety gate." Detection hint: enumerate every code path that can produce hardware-output frames, not just the normal pipeline; any path that writes to `_stream_frames` or `_send_emergency_stop` without traversing `laser_vector_interlock` is a bypass. (Sibling to LS1.)
- **LS3b** — "Safety-critical watchdog shares GIL/interpreter state with the workload it monitors." Detection hint: any `SafetyMonitor` / `HeartbeatWatchdog` implemented as `threading.Thread` MUST be documented as providing NO bounded-latency guarantee during C-extension stalls. Production-grade systems use `multiprocessing.Process` + SIGKILL, or accept the limitation explicitly.
- **A11b** — "Hot-path cost attributed to a component without benchmark." Detection hint: any plan that proposes an optimization with a claimed cost reduction must include an in-repo benchmark pin for the CURRENT cost before the fix is written.

---

## Sources (research from cycle-1 still valid)

- [ILDA — How to do safe audience scanning](https://www.ilda.com/audiencescanningsafety.htm)
- [Pangolin PASS](https://pangolin.com/products/pass)
- [LVR Optical — Laser scan-fail safeguards](https://www.lvroptical.com/blog-Scan-fail.html)
- [PEP 703 — Making the Global Interpreter Lock Optional in CPython](https://peps.python.org/pep-0703/)
- [Python `multiprocessing.shared_memory`](https://docs.python.org/3/library/multiprocessing.shared_memory.html)
- Panel reports cycle-1 (internal): Codex, Gemini, Kilo, Claude R1 reviews at `/tmp/deferred_plan_panel/`.
