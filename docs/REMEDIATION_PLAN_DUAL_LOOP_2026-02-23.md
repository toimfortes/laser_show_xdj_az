# Remediation Plan: Real-Time Stability + Safety Hardening

Date: 2026-02-23
Scope: Address the deep-research findings for deterministic operation with current hardware scope (single OEM 7CH laser + Pknight Art-Net/DMX).
**STATUS: STOP** (Plan approved for execution; release GO is blocked until Decision Gates G1-G6 pass with fresh implementation evidence.)

## Goals
1. Eliminate crash/deadlock classes in the live loop.
2. Bring worst-case frame processing below 20 ms at 50 Hz target.
3. Keep safety ownership in the fast path regardless of AI/orchestration load.
4. Prepare an incremental migration to dual-loop architecture without a full rewrite.

## Non-Goals (for this plan)
1. No expansion to additional fixtures/hardware.
2. No full replacement of all DSP libraries in one step.
3. No API/web route changes.

## Phase 0: Baseline + Guardrails (2-3 days)

Deliverables:
1. Add runtime timing telemetry with p50/p95/p99 for each node and full-frame wall time.
2. Add stress harness: 60s/300s mock runs asserting max frame time and no unhandled exceptions.
3. Define hard budgets:
- Fast loop frame budget: 20 ms (target), 25 ms (soft fail), 35 ms (hard fail)
- DMX TX cadence budget: <= 5 ms jitter at configured refresh

Acceptance gates:
1. `pytest -q` all green.
2. New performance tests pass on target laptop profile.
3. Zero unhandled exceptions in 300s soak test.

## Phase 1: Crash/Deadlock and Contention Fixes (5-7 days)

Work items:
1. Protect audio buffer snapshot/callback mutation boundary.
2. Replace watchdog direct blackout lock path with non-blocking emergency signal.
3. Move CV capture/processing out of synchronous graph call path.
4. Refactor DMX command apply to double-buffer commit (compute outside lock, swap inside lock).
5. Improve frame pacing: coarse sleep + short spin/yield tail.

Acceptance gates:
1. No `deque mutated during iteration` under concurrent stress test.
2. Watchdog blackout still executes when main graph is intentionally stalled.
3. p99 frame time improves and remains below soft fail threshold in mock and live-no-CV modes.

## Phase 2: Hot-Loop DSP Slimdown (2-3 weeks)

Work items:
1. Replace per-frame full-buffer feature recomputation with streaming/block incremental feature extraction.
2. Keep current feature contract shape so downstream nodes are unaffected.
3. Re-calibrate thresholds for structure detection after DSP backend change.

Acceptance gates:
1. Feature node p99 cost reduced by at least 50% from baseline.
2. End-to-end fast loop p99 under 20 ms with CV disabled and under 25 ms with CV enabled.
3. Structure behavior parity tests pass on canned tracks.

## Phase 3: Dual-Loop Separation (3-6 weeks)

Work items:
1. Introduce Fast Loop runtime (50 Hz): audio ingest, incremental DSP, MIDI ingest, safety, DMX TX.
2. Keep LangGraph as Slow Loop (1-5 Hz): scene/director strategy and heavier inference.
3. Introduce bounded shared contract between loops:
- Fast->Slow: compact sensor summary
- Slow->Fast: high-level intent (scene/style/budgets), never raw DMX writes
4. Enforce ownership rule in code: only Fast Loop can mutate universe and safety-critical channels.

Acceptance gates:
1. Fast loop timing unaffected by induced slow-loop CPU spikes.
2. Safety interlock behavior unchanged under slow-loop stall/failure.
3. Blackout path remains independent and deterministic.

## Fast/Slow IPC Contract (v1)

Contract version: `fast_slow_contract_v1`

Fast->Slow payload (50 Hz producer, 1-5 Hz consumer):
1. `ts_monotonic_ms: int` (producer timestamp)
2. `frame_number: int`
3. `rms_energy: float` (`0.0..1.0`)
4. `low_energy: float` (`0.0..1.0`)
5. `mid_energy: float` (`0.0..1.0`)
6. `high_energy: float` (`0.0..1.0`)
7. `beat_bpm: float` (`>0`)
8. `beat_phase: float` (`0.0..1.0`)
9. `beat_confidence: float` (`0.0..1.0`)
10. `drop_probability: float` (`0.0..1.0`)
11. `midi_filter_avg: float` (`0.0..1.0`)
12. `sensor_health: dict[str, bool]`

Slow->Fast payload (advisory only; never direct DMX):
1. `intent_version: int`
2. `intent_ts_monotonic_ms: int`
3. `target_scene: str`
4. `energy_bias: float` (`-1.0..1.0`)
5. `movement_style: str`
6. `color_theme: str`
7. `strobe_budget_hz: float` (`>=0`)
8. `intent_ttl_ms: int` (default `1000`)

Ownership rules:
1. Fast loop is sole writer for DMX universe, blackout latch, and safety channels.
2. Slow loop intent expires when `now_ms - intent_ts_monotonic_ms > intent_ttl_ms`.
3. Expired/invalid intent reverts fast loop to safe local defaults.

## Blackout SLA and Safety SLOs

1. Watchdog timeout to blackout-latch set: <= 10 ms (target), <= 20 ms (hard limit).
2. Blackout-latch to first zero-output DMX/Art-Net frame queued: <= 25 ms (hard limit).
3. Full-output-to-zero visible on fixture: <= 100 ms (hardware smoke test limit).
4. Any breach of (1) or (2) is automatic STOP for release.

## Feature Flags and Rollout Controls

| Flag | Default | Phase | Purpose | Rollback |
|---|---|---|---|---|
| `PHOTONIC_CV_THREADED` | `true` | 1 | Move CV capture off main loop | set `false` to restore inline path |
| `PHOTONIC_DMX_DOUBLE_BUFFER` | `true` | 1 | Compute universe outside output lock | set `false` for legacy lock path |
| `PHOTONIC_HYBRID_PACING` | `true` | 1 | sleep + short spin tail for frame stability | set `false` for sleep-only pacing |
| `PHOTONIC_STREAMING_DSP` | `false` | 2 | Enable incremental DSP backend | set `false` to return to legacy extraction |
| `PHOTONIC_DUAL_LOOP` | `false` | 3 | Split fast/slow loop runtime | set `false` to run single-loop path |

## Risk Register (Owners + Dates)

| Risk ID | Risk | Severity | Owner | Target Date | Mitigation | Status |
|---|---|---|---|---|---|---|
| R1 | Audio callback/state race | CRITICAL | Runtime | 2026-02-27 | lock/snapshot boundary + stress test | OPEN |
| R2 | Watchdog blackout blocked by lock contention | CRITICAL | Runtime | 2026-02-27 | atomic blackout latch + TX-thread enforcement | OPEN |
| R3 | CV blocking main loop | HIGH | Runtime | 2026-02-27 | threaded capture cache + non-blocking reads | OPEN |
| R4 | DMX lock contention | HIGH | DMX | 2026-03-02 | double-buffer commit path | OPEN |
| R5 | DSP cost exceeds 20 ms budget | HIGH | DSP | 2026-03-14 | incremental feature pipeline + retune thresholds | OPEN |
| R6 | Dual-loop stale intent | MEDIUM | Runtime | 2026-04-06 | TTL + monotonic timestamps + safe fallback | OPEN |

## Decision Gates (STOP/GO)

| Gate | Check | Command/Evidence | Pass Rule | Action on Fail |
|---|---|---|---|---|
| G1 | Plan preflight | `python scripts/audit/plan_preflight.py --plan-file docs/REMEDIATION_PLAN_DUAL_LOOP_2026-02-23.md` | rc=0 | STOP |
| G2 | Route parity | `python scripts/audit/route_parity_check.py --plan-file docs/REMEDIATION_PLAN_DUAL_LOOP_2026-02-23.md` | rc=0 | STOP |
| G3 | Unit/integration suite | `pytest -q` | all pass | STOP |
| G4 | Type/lint | `mypy src && ruff check src tests` | all pass | STOP |
| G5 | 300s soak | perf harness report | no unhandled exceptions; frame p99 within budget | STOP |
| G6 | Blackout SLA | hardware smoke report | all SLA limits satisfied | STOP |
| G7 | Planned-symbol realization | `rg -n "def request_blackout|_cached_state|runtime_flags|cv_threaded|dmx_double_buffer|hybrid_pacing|streaming_dsp|dual_loop" src/photonic_synesthesia` | required symbols present in implementation | STOP |

---

## Integration Contracts

### Integration Contract: Audio Callback -> State Snapshot

**Why this boundary exists:** Real-time callback producer and graph consumer share audio sample memory.

**Caller (anchor):** `src/photonic_synesthesia/graph/nodes/audio_sense.py:62`  
**Callee (anchor):** `src/photonic_synesthesia/graph/nodes/audio_sense.py:143`

**Call expression (verbatim):**
```python
with self._buffer_lock:
    self._buffer.extend(mono.tolist())
```

**Callee signature (verbatim):**
```python
def __call__(self, state: PhotonicState) -> PhotonicState:
```

**Request/Source schema (verbatim, if applicable):**
```python
self._buffer: deque[float]
state["audio_buffer"]: list[float]
```

**Argument mapping + type chain (REQUIRED):**

| Arg | Required? | Source expression | Type@Source | Type@Callee | Conversion | Notes |
|---|---|---|---|---|---|---|
| audio samples | yes | `self._buffer` | `deque[float]` | `list[float]` | `list(...)` | snapshot must be under same lock as writer |

**Missing required inputs (if any):**
- none

**Incompatible types (if any):**
- none

**Return/Response contract (REQUIRED):**
- **Return value shape:** `PhotonicState`
- **Caller expects:** updated `PhotonicState`
- **Mismatch?** no

**Verdict:** PASS

### Integration Contract: Heartbeat Watchdog -> DMX Emergency Blackout Signal

**Why this boundary exists:** Independent watchdog must force blackout without depending on graph-loop liveness.

**Caller (anchor):** `src/photonic_synesthesia/graph/nodes/safety_interlock.py:86`  
**Callee (anchor):** `src/photonic_synesthesia/graph/nodes/dmx_output.py` (planned addition: `request_blackout()`)

**Call expression (verbatim):**
```python
self._on_timeout()
```

**Callee signature (verbatim):**
```python
def request_blackout(self) -> None:
```

**Request/Source schema (verbatim, if applicable):**
```python
Heartbeat timeout event
```

**Argument mapping + type chain (REQUIRED):**

| Arg | Required? | Source expression | Type@Source | Type@Callee | Conversion | Notes |
|---|---|---|---|---|---|---|
| timeout event | yes | watchdog callback invocation | event | none | none | callback must be non-blocking |

**Missing required inputs (if any):**
- none

**Incompatible types (if any):**
- none

**Return/Response contract (REQUIRED):**
- **Return value shape:** `None`
- **Caller expects:** side-effect latch set
- **Mismatch?** no

**Verdict:** PASS

### Integration Contract: CV Worker Thread -> Graph Read Path

**Why this boundary exists:** CV acquisition must not block frame loop.

**Caller (anchor):** `src/photonic_synesthesia/graph/nodes/cv_sense.py:74`  
**Callee (anchor):** `src/photonic_synesthesia/graph/nodes/cv_sense.py:100`

**Call expression (verbatim):**
```python
self._cached_state = CVState(...)
```

**Callee signature (verbatim):**
```python
def __call__(self, state: PhotonicState) -> PhotonicState:
```

**Request/Source schema (verbatim, if applicable):**
```python
self._cached_state: CVState
state["cv_state"]: CVState
```

**Argument mapping + type chain (REQUIRED):**

| Arg | Required? | Source expression | Type@Source | Type@Callee | Conversion | Notes |
|---|---|---|---|---|---|---|
| cv snapshot | yes | `self._cached_state` | `CVState` | `CVState` | none | protected by lock on read/write |

**Missing required inputs (if any):**
- none

**Incompatible types (if any):**
- none

**Return/Response contract (REQUIRED):**
- **Return value shape:** `PhotonicState`
- **Caller expects:** updated `PhotonicState`
- **Mismatch?** no

**Verdict:** PASS

### Integration Contract: Fixture Commands -> DMX Universe Commit

**Why this boundary exists:** Command application and transport thread share universe memory.

**Caller (anchor):** `src/photonic_synesthesia/graph/nodes/dmx_output.py:215`  
**Callee (anchor):** `src/photonic_synesthesia/graph/nodes/dmx_output.py:242`

**Call expression (verbatim):**
```python
state["fixture_commands"]
```

**Callee signature (verbatim):**
```python
def __call__(self, state: PhotonicState) -> PhotonicState:
```

**Request/Source schema (verbatim, if applicable):**
```python
list[FixtureCommand] -> bytearray universe
```

**Argument mapping + type chain (REQUIRED):**

| Arg | Required? | Source expression | Type@Source | Type@Callee | Conversion | Notes |
|---|---|---|---|---|---|---|
| channel | yes | `cmd["channel_values"].keys()` | `int` | `int` | range clamp | must stay 1..512 |
| value | yes | `cmd["channel_values"].values()` | `int|float` | `int` | finite-check + clamp | reject NaN/Inf |

**Missing required inputs (if any):**
- none

**Incompatible types (if any):**
- none

**Return/Response contract (REQUIRED):**
- **Return value shape:** updated `PhotonicState` with `dmx_universe`
- **Caller expects:** committed frame data
- **Mismatch?** no

**Verdict:** PASS

### Integration Contract: Slow Loop Intent -> Fast Loop Safety/DMX Ownership

**Why this boundary exists:** Director/scene intent influences output but must not bypass safety.

**Caller (anchor):** `src/photonic_synesthesia/graph/nodes/scene_select.py:77`  
**Callee (anchor):** `src/photonic_synesthesia/graph/nodes/interpreter.py:21`

**Call expression (verbatim):**
```python
state["director_state"]
state["fixture_commands"]
```

**Callee signature (verbatim):**
```python
def interpret(self, commands: list[FixtureCommand], strobe_budget_hz: float) -> list[FixtureCommand]:
```

**Request/Source schema (verbatim, if applicable):**
```python
DirectorState.strobe_budget_hz
list[FixtureCommand]
```

**Argument mapping + type chain (REQUIRED):**

| Arg | Required? | Source expression | Type@Source | Type@Callee | Conversion | Notes |
|---|---|---|---|---|---|---|
| commands | yes | `state["fixture_commands"]` | `list[FixtureCommand]` | `list[FixtureCommand]` | none | intent is advisory |
| strobe budget | yes | `state["director_state"]["strobe_budget_hz"]` | `float` | `float` | `float(...)` | safety layer clamps |

**Missing required inputs (if any):**
- none

**Incompatible types (if any):**
- none

**Return/Response contract (REQUIRED):**
- **Return value shape:** constrained `list[FixtureCommand]`
- **Caller expects:** safe commands for safety interlock + DMX
- **Mismatch?** no

**Verdict:** PASS

### Integration Contract: Environment Flags -> Runtime Execution Paths

**Why this boundary exists:** Feature flags in the plan must resolve into typed config and be consumed by runtime wiring.

**Caller (anchor):** `src/photonic_synesthesia/core/config.py:146` (`Settings` + env prefix)  
**Callee (anchor):** `src/photonic_synesthesia/graph/builder.py:116` (runtime wiring) and node constructors

**Call expression (verbatim):**
```python
settings = Settings.from_yaml(...)
graph = build_photonic_graph(settings, mock_sensors=mock)
```

**Callee signature (verbatim):**
```python
def build_photonic_graph(
    settings: Settings | None = None,
    mock_sensors: bool = False,
) -> PhotonicGraph:
```

**Request/Source schema (verbatim, if applicable):**
```python
model_config = SettingsConfigDict(
    env_prefix="PHOTONIC_",
    env_nested_delimiter="__",
)
```

**Argument mapping + type chain (REQUIRED):**

| Arg | Required? | Source expression | Type@Source | Type@Callee | Conversion | Notes |
|---|---|---|---|---|---|---|
| `cv_threaded` | yes | `PHOTONIC_CV_THREADED` | `str` env | `bool` | explicit parse (`true/false/1/0`) | new typed runtime flag required |
| `dmx_double_buffer` | yes | `PHOTONIC_DMX_DOUBLE_BUFFER` | `str` env | `bool` | explicit parse | consumed by `DMXOutputNode` |
| `hybrid_pacing` | yes | `PHOTONIC_HYBRID_PACING` | `str` env | `bool` | explicit parse | consumed by `PhotonicGraph.run_loop` |
| `streaming_dsp` | yes | `PHOTONIC_STREAMING_DSP` | `str` env | `bool` | explicit parse | consumed by feature node factory |
| `dual_loop` | yes | `PHOTONIC_DUAL_LOOP` | `str` env | `bool` | explicit parse | selects fast/slow runtime mode |

**Missing required inputs (if any):**
- none (planned addition must add a typed `runtime_flags` config section)

**Incompatible types (if any):**
- `str` env to `bool` runtime is incompatible without explicit parser (CRITICAL if omitted)

**Return/Response contract (REQUIRED):**
- **Return value shape:** `PhotonicGraph` (single-loop) or dual-loop runtime wrapper
- **Caller expects:** deterministic runtime with feature-flag selected behavior
- **Mismatch?** no (once typed flags + parser are implemented)

**Verdict:** PASS (planned; blocked by G7 until symbols exist)

---

## Verification Matrix

1. Unit: audio callback/snapshot concurrency (no runtime error over repeated races).
2. Unit: watchdog timeout while main DMX path is blocked still results in blackout latch.
3. Unit: CV `__call__` executes without screen-capture I/O in loop.
4. Integration: 300s run with mocks; no unhandled exceptions; max frame below threshold.
5. Integration: induced CPU pressure on slow loop does not violate fast-loop jitter budget.
6. Hardware smoke: Pknight + laser blackout path measured end-to-end.

## Delta Re-Critique List (R98)

Changed/new boundary claims introduced in this patch:
1. Fast/slow loop IPC schema and TTL behavior.
2. Watchdog to `request_blackout()` callback contract.
3. Feature-flagged execution path branching for CV/DMX/DSP/Dual-loop.
4. Explicit environment-flag ingestion and boolean parse contract into runtime wiring.

Required re-checks before marking complete:
1. Re-run V105 integration contract validation for all three changed boundaries.
2. Re-run V106 route parity (no route deltas expected).
3. Re-run gate table commands G1-G2 and attach fresh evidence timestamps.

## Rollback Strategy

1. Keep feature flags for CV threaded mode and hybrid pacing.
2. Keep old processing path behind config switches for one release.
3. If latency regression occurs, disable new CV thread and keep fast-loop-only fixes while investigating.

## Risks and Mitigations

1. Risk: spin-wait increases CPU.
- Mitigation: cap busy window (<=2 ms), expose config toggle.
2. Risk: DSP backend change alters structure classifier behavior.
- Mitigation: add calibration fixture tracks and threshold-fit script.
3. Risk: dual-loop introduces stale intent.
- Mitigation: timestamped intent payloads + TTL invalidation in fast loop.

## Evidence Receipts (Row-Atomic)

| ID | Command | CWD | RC | stdout_sha256 | stderr_sha256 |
|---|---|---|---:|---|---|
| `P-G1` | `python scripts/audit/plan_preflight.py --plan-file docs/REMEDIATION_PLAN_DUAL_LOOP_2026-02-23.md` | `.` | `0` | `4b1340a3e054544daaa8353757b30b4dc00db73095a624fc2b2cc03069ed40d9` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `P-G2` | `python scripts/audit/route_parity_check.py --plan-file docs/REMEDIATION_PLAN_DUAL_LOOP_2026-02-23.md` | `.` | `0` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `P-G3` | `python scripts/audit/critique_preflight.py --spec-path schemas/critique_spec_dual_loop_plan.json --matter-map-path data/critique/matter_map_dual_loop_plan.json --evidence-path data/critique/evidence_dual_loop_plan.jsonl` | `.` | `0` | `4dd674457b7f0443df83f748e4580ed740636e33a68d89c2f327f0292e5770b5` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `P-G4` | `rg -n -e "def request_blackout" -e "_cached_state" -e "runtime_flags" -e "cv_threaded" -e "dmx_double_buffer" -e "hybrid_pacing" -e "streaming_dsp" -e "dual_loop" src/photonic_synesthesia` | `.` | `0` | `a2fe5c6e289d009fb4c2eb2f6a827bf6cf2896886ecd793fcbd83bfdc6d3937d` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
