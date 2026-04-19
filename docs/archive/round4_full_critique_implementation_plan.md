# Round 4 Full Implementation Plan (Critique Implementation v1.39)

## 0) Quick Summary

- Objective: remediate safety-critical output-path flaws and close high-impact technical debt using the forensic standards in `docs/reference/critique_implementation.md`.
- Primary outcome: guarantee that only safety-validated DMX universes can be transmitted.
- Secondary outcomes: eliminate safety no-op branches, add integration-level proof tests, and modernize configuration/tooling deprecations.
- Delivery model: phased implementation with hard STOP/GO gates, explicit integration contracts (V105), and post-fix re-critique after each phase.

## 1) Required Inputs (V90)

| Input | Status | Evidence Anchor |
|---|---|---|
| Plan | Present | `docs/round4_full_critique_implementation_plan.md` |
| Guide | Present | `docs/reference/critique_implementation.md` |
| Files | Present | `src/photonic_synesthesia/graph/builder.py`, `src/photonic_synesthesia/graph/nodes/dmx_output.py`, `src/photonic_synesthesia/graph/nodes/safety_interlock.py`, `src/photonic_synesthesia/interpreters/safety.py`, `src/photonic_synesthesia/graph/nodes/midi_sense.py`, `src/photonic_synesthesia/graph/nodes/fusion.py`, `src/photonic_synesthesia/core/config.py` |
| Functions | Present | `build_photonic_graph`, `DMXOutputNode.__call__`, `DMXOutputNode.blackout`, `SafetyInterlockNode.__call__`, `InterpreterNode.__call__` |
| Decisions | Present | Prior direction anchored in `docs/round3_vfinal_critique_implementation_plan.md:5`, `docs/round3_vfinal_critique_implementation_plan.md:41`, `docs/round3_vfinal_critique_implementation_plan.md:68` |
| Diffs | Pending | Must be captured post-edit with `git diff --name-only` and `git diff --stat` |

## 2) Baseline Forensic Snapshot (Before Changes)

Date baseline captured: 2026-02-20 (local run).

| Check | Command | Result |
|---|---|---|
| Unit tests | `pytest -q` | PASS (14 passed, 1 warning) |
| Lint | `ruff check src tests` | PASS (with Ruff config deprecation warning) |
| Types | `mypy src` | PASS |
| Safety ordering probe | local runtime probe (DMX then interlock) | FAIL: state is clamped but `DMXOutputNode._universe` remains unsafe |

Baseline critical finding:
- Runtime wiring currently sends `interpreter -> dmx_output -> safety_interlock` (`src/photonic_synesthesia/graph/builder.py:227`, `src/photonic_synesthesia/graph/builder.py:230`).
- `DMXOutputNode.__call__` mutates transmitter-owned `_universe` before interlock (`src/photonic_synesthesia/graph/nodes/dmx_output.py:233`).
- `SafetyInterlockNode.__call__` mutates `state["dmx_universe"]` only (`src/photonic_synesthesia/graph/nodes/safety_interlock.py:246`).
- This violates the intended safety contract and permits unsafe internal output state.

## 3) Scope and Ownership

| File | Scope Role | Change Type | Owner |
|---|---|---|---|
| `src/photonic_synesthesia/graph/builder.py` | enforce safe node ordering contract | functional wiring | Graph Runtime Engineer |
| `src/photonic_synesthesia/graph/nodes/dmx_output.py` | separate command-apply from transmit-owned universe commit | API/contract refactor | DMX Runtime Engineer |
| `src/photonic_synesthesia/graph/nodes/safety_interlock.py` | finalize interlock logic, complete strobe/degradation branches | safety logic update | Safety Engineer |
| `src/photonic_synesthesia/interpreters/safety.py` | align channel-base logic with fixture addressing contract | correctness fix | Safety Engineer |
| `src/photonic_synesthesia/graph/nodes/midi_sense.py` | close TODO-derived fidelity gaps (EQ/effects placeholders) | behavior completion | Input Pipeline Engineer |
| `src/photonic_synesthesia/graph/nodes/fusion.py` | remove no-op filter branches, make deterministic outputs | behavior completion | Input Pipeline Engineer |
| `src/photonic_synesthesia/core/config.py` | migrate Pydantic config style (v2+ forward compatibility) | maintenance | Platform Engineer |
| `pyproject.toml` | migrate Ruff settings to `tool.ruff.lint` schema | maintenance | Platform Engineer |
| `tests/unit/test_safety_interlock.py` | extend branch and ownership coverage | test expansion | QA Engineer |
| `tests/unit/test_interpreter_node.py` | enforce corrected channel-base contract | test expansion | QA Engineer |
| `tests/integration/test_output_safety_ordering.py` [NEW] | prove unsafe frame cannot transmit | integration test | QA Engineer |
| `tests/integration/test_watchdog_blackout_path.py` [NEW] | prove deterministic watchdog blackout path | integration test | QA Engineer |
| `tests/property/test_safety_invariants.py` [NEW] | DMX/safety invariants over broad input space | property test | QA Engineer |

## 4) Integration Contracts (V105)

### Integration Contract: Interpreter -> Interlock -> Output Commit

**Why this boundary exists:** fixture commands must be safety-constrained, then interlocked, then committed to transmitter state.

**Caller (anchor):** `src/photonic_synesthesia/graph/builder.py:227` (current edge region)  
**Callee (anchor):** `src/photonic_synesthesia/graph/nodes/safety_interlock.py:150`, `src/photonic_synesthesia/graph/nodes/dmx_output.py:229`

**Call expression (verbatim, planned):**
```python
graph.add_edge("interpreter", "safety_interlock")
graph.add_edge("safety_interlock", "dmx_output")
```

**Callee signature (verbatim, planned):**
```python
def __call__(self, state: PhotonicState) -> PhotonicState: ...
```

**Request/Source schema (verbatim, applicable fields):**
```python
PhotonicState[
    "fixture_commands": list[FixtureCommand],
    "dmx_universe": bytes,
    "safety_state": SafetyState,
]
```

**Argument mapping + type chain (REQUIRED):**

| Arg | Required? | Source expression | Type@Source | Type@Callee | Conversion | Notes |
|---|---|---|---|---|---|---|
| `state` | yes | graph edge payload | `PhotonicState` | `PhotonicState` | none | invariant across nodes |
| `fixture_commands` | yes | `state["fixture_commands"]` | `list[FixtureCommand]` | interlock read path | none | interlock must validate commands before commit |
| `dmx_universe` | yes | `state["dmx_universe"]` | `bytes` | output commit path | `bytes(...)` where needed | canonical final frame buffer |

**Missing required inputs (if any):**
- none (target contract requires state keys remain mandatory).

**Incompatible types (if any):**
- none expected; FAIL if `fixture_commands` is consumed before interlock.

**Return/Response contract (REQUIRED):**
- Return value shape: `PhotonicState` with safety-approved `dmx_universe` and cleared/consumed command payload.
- Caller expects: same mutable state object semantics as current graph.
- Response model (if API): not applicable.
- Mismatch: CRITICAL if output node mutates private universe before interlock verdict.

**Failure modes / status codes (REQUIRED for API boundaries):**
| Failure | Trigger | Where raised | HTTP code (if any) | Caller behavior |
|---|---|---|---|---|
| unsafe pre-interlock transmit | output commit before interlock | `src/photonic_synesthesia/graph/nodes/dmx_output.py` | n/a | STOP |
| silent state/output divergence | interlock mutates state only | `src/photonic_synesthesia/graph/nodes/safety_interlock.py` | n/a | STOP |

**Verdict:** FAIL currently, target PASS in Phase 1.

### Integration Contract: SafetyInterlock -> DMXOutput Blackout Surface

**Why this boundary exists:** watchdog and emergency branches must use one atomic blackout mechanism.

**Caller (anchor):** `src/photonic_synesthesia/graph/nodes/safety_interlock.py:135`  
**Callee (anchor):** `src/photonic_synesthesia/graph/nodes/dmx_output.py:258`

**Call expression (verbatim):**
```python
self._heartbeat_watchdog = HeartbeatWatchdog(
    on_timeout=dmx_output.blackout,
    timeout_s=self.config.heartbeat_timeout_s,
)
```

**Callee signature (verbatim):**
```python
def blackout(self) -> None: ...
```

**Request/Source schema (verbatim, if applicable):**
```python
SafetyConfig.heartbeat_timeout_s: float
```

**Argument mapping + type chain (REQUIRED):**

| Arg | Required? | Source expression | Type@Source | Type@Callee | Conversion | Notes |
|---|---|---|---|---|---|---|
| `on_timeout` | yes | `dmx_output.blackout` | `Callable[[], None]` | `Callable[[], None]` | none | must remain non-blocking and idempotent |
| `timeout_s` | yes | `self.config.heartbeat_timeout_s` | `float` | `float` | none | clamped in watchdog constructor |

**Missing required inputs (if any):**
- none.

**Incompatible types (if any):**
- none.

**Return/Response contract (REQUIRED):**
- Return value shape: side effect only (output universe zeroed).
- Caller expects: blackout reaches transmit-owned state, not only graph state.
- Response model: n/a.
- Mismatch: CRITICAL if blackout does not update transmit-owned buffer.

**Failure modes / status codes (REQUIRED for API boundaries):**
| Failure | Trigger | Where raised | HTTP code (if any) | Caller behavior |
|---|---|---|---|---|
| watchdog timeout without blackout | stalled loop + no side effect | watchdog thread | n/a | STOP |

**Verdict:** PARTIAL PASS currently; must become deterministic PASS in Phase 1.

### Integration Contract: Fixture Commands -> Interpreter Channel Base Resolution

**Why this boundary exists:** incorrect channel base derivation can apply safety clamps to wrong channels.

**Caller (anchor):** `src/photonic_synesthesia/graph/nodes/fixture_control.py:103`  
**Callee (anchor):** `src/photonic_synesthesia/interpreters/safety.py:34`

**Call expression (verbatim):**
```python
state["fixture_commands"] = self.interpreter.interpret(
    state["fixture_commands"],
    strobe_budget_hz=strobe_budget,
)
```

**Callee signature (verbatim):**
```python
def interpret(self, commands: list[FixtureCommand], strobe_budget_hz: float) -> list[FixtureCommand]: ...
```

**Request/Source schema (verbatim, applicable fields):**
```python
FixtureCommand = {
    "fixture_id": str,
    "fixture_type": str,
    "channel_values": dict[int, int],
}
```

**Argument mapping + type chain (REQUIRED):**

| Arg | Required? | Source expression | Type@Source | Type@Callee | Conversion | Notes |
|---|---|---|---|---|---|---|
| `commands` | yes | `state["fixture_commands"]` | `list[FixtureCommand]` | `list[FixtureCommand]` | none | fixture start address must remain inferable |
| `strobe_budget_hz` | yes | `float(state["director_state"]["strobe_budget_hz"])` | `float` | `float` | `float(...)` | already explicit |

**Missing required inputs (if any):**
- potential: explicit fixture start address is not carried in command schema.

**Incompatible types (if any):**
- semantic mismatch risk: `base = min(channel_values.keys())` can be wrong if map is sparse.

**Return/Response contract (REQUIRED):**
- Return value shape: same command list with clamped and smoothed values.
- Caller expects: command safety constraints align with actual fixture channels.
- Response model: n/a.
- Mismatch: HIGH if sparse channel maps shift interpreted offsets.

**Failure modes / status codes (REQUIRED for API boundaries):**
| Failure | Trigger | Where raised | HTTP code (if any) | Caller behavior |
|---|---|---|---|---|
| wrong Y/speed/strobe channel clamped | sparse map and inferred base wrong | `interpreters/safety.py` | n/a | STOP |

**Verdict:** FAIL until base-address contract is explicit and tested.

### Integration Contract: Scene Selection -> Fixture Control Behavior Parity

**Why this boundary exists:** scene JSON is selected but fixture control largely ignores scene payload details.

**Caller (anchor):** `src/photonic_synesthesia/graph/nodes/scene_select.py:74`  
**Callee (anchor):** `src/photonic_synesthesia/graph/nodes/fixture_control.py:56`

**Call expression (verbatim, current):**
```python
scene = state["scene_state"]["current_scene"]
```

**Callee signature (verbatim):**
```python
def __call__(self, state: PhotonicState) -> PhotonicState: ...
```

**Request/Source schema (verbatim, applicable fields):**
```python
SceneState = {
    "current_scene": str,
    "pending_scene": str | None,
    "transition_progress": float,
    ...
}
```

**Argument mapping + type chain (REQUIRED):**

| Arg | Required? | Source expression | Type@Source | Type@Callee | Conversion | Notes |
|---|---|---|---|---|---|---|
| `current_scene` | yes | `state["scene_state"]["current_scene"]` | `str` | `str` | none | only scene name is consumed today |
| `scene payload` | optional target | `SceneSelectNode.scenes[current_scene]` | `dict[str, Any]` | fixture behavior model | typed model planned | implement in Phase 3 |

**Missing required inputs (if any):**
- structured scene payload is not propagated to fixture nodes.

**Incompatible types (if any):**
- none hard, but current design is under-specified.

**Return/Response contract (REQUIRED):**
- Return value shape: command stream reflects selected scene semantics.
- Caller expects: scene selection meaningfully alters fixture behavior.
- Response model: n/a.
- Mismatch: MEDIUM if scene files exist but are not behaviorally consumed.

**Failure modes / status codes (REQUIRED for API boundaries):**
| Failure | Trigger | Where raised | HTTP code (if any) | Caller behavior |
|---|---|---|---|---|
| scene-selection no-op drift | scene metadata unused by control nodes | fixture control path | n/a | degrade quality; not immediate STOP |

**Verdict:** PARTIAL PASS; target full parity in Phase 3.

## 5) Route Reality (V106)

- This plan introduces no API/webhook route claims.
- Therefore no `[NEW]`, `[FRONTEND]`, `[EXTERNAL]`, or `[DEAD]` route annotations are required in scope statements.
- Mandatory validation still runs: `python scripts/audit/route_parity_check.py --plan-file docs/round4_full_critique_implementation_plan.md`.

## 6) Phased Implementation

### Phase 1: Safety Correctness (Blocking)

Goal: eliminate unsafe transmit ordering and close active safety no-op branches.

Tasks:
1. Rewire graph ordering to `interpreter -> safety_interlock -> dmx_output` in `src/photonic_synesthesia/graph/builder.py`.
2. Refactor output contract so `DMXOutputNode` commits only safety-approved frame data.
3. Implement missing strobe cooldown behavior in `SafetyInterlockNode.__call__`.
4. Implement graceful degradation behavior for low beat confidence in `SafetyInterlockNode.__call__`.
5. Fix interpreter base-channel inference to avoid sparse-map offset errors.
6. Add integration proof test `tests/integration/test_output_safety_ordering.py` [NEW].
7. Add integration proof test `tests/integration/test_watchdog_blackout_path.py` [NEW].

Acceptance criteria:
- Unsafe command values cannot enter transmit-owned universe.
- Interlock modifies the exact frame that output thread transmits.
- Strobe cooldown branch and degradation branch have executable logic and branch coverage.
- Watchdog timeout blackouts are deterministic within configured threshold window.

### Phase 2: Runtime Reliability and Determinism

Goal: remove non-deterministic no-op behavior in input fusion/control paths.

Tasks:
1. Implement MIDI EQ/effects tracking placeholders in `src/photonic_synesthesia/graph/nodes/midi_sense.py`.
2. Replace fusion filter-path `pass` branches with deterministic intensity modifiers in `src/photonic_synesthesia/graph/nodes/fusion.py`.
3. Add/expand tests for new fusion and MIDI behaviors.
4. Validate runtime stability under mock pipeline loop.

Acceptance criteria:
- No active TODO/pass placeholders in runtime decision branches.
- Fusion outputs deterministic transformations for high-pass and low-pass conditions.
- New behavior covered by unit tests.

### Phase 3: Maintainability and Forward Compatibility

Goal: align configuration/tooling with current standards and reduce latent drift.

Tasks:
1. Migrate `Settings` config style in `src/photonic_synesthesia/core/config.py` to Pydantic v2 `model_config` / `SettingsConfigDict` semantics.
2. Migrate Ruff config schema in `pyproject.toml` to `tool.ruff.lint.*` keys.
3. Add property-based invariants in `tests/property/test_safety_invariants.py` [NEW].
4. Begin typed scene/profile composition path so selected scenes can drive fixture semantics (non-breaking).

Acceptance criteria:
- Baseline deprecation warnings addressed for config and lint schema.
- Property tests enforce DMX bounds and safety invariants.
- Scene-to-control typed interface introduced without breaking existing behavior.

## 7) Verification Matrix and Gates

### Global verification commands (run after each phase)

```bash
pytest -q
ruff check src tests
mypy src
```

### Phase-specific verification

```bash
# Phase 1
pytest -q tests/unit/test_safety_interlock.py
pytest -q tests/unit/test_interpreter_node.py
pytest -q tests/integration/test_output_safety_ordering.py
pytest -q tests/integration/test_watchdog_blackout_path.py

# Phase 2
pytest -q tests/unit

# Phase 3
pytest -q tests/property/test_safety_invariants.py
```

### STOP/GO table

| Gate | Condition | Expected Pair |
|---|---|---|
| G1 | output ordering proven safe by integration test | PASS + PROCEED |
| G2 | watchdog blackout deterministic and verified | PASS + PROCEED |
| G3 | no safety-critical no-op branch remains active | PASS + PROCEED |
| G4 | lint/types/tests clean for touched scope | PASS + PROCEED |
| G5 | phase-specific checks pass | PASS + PROCEED |

Gate policy:
- Any FAIL in G1-G4 is STOP.
- Proceed to next phase only when all gates for current phase are PASS.

## 8) Risk Register

| Risk ID | Severity | Description | Mitigation | Owner | Target Phase |
|---|---|---|---|---|---|
| R4-SAFE-1 | CRITICAL | unsafe values written to transmit-owned universe before interlock | reorder graph + output commit contract + integration tests | Safety Engineer | Phase 1 |
| R4-SAFE-2 | CRITICAL | watchdog timeout does not guarantee on-wire blackout | enforce single blackout surface + deterministic timeout tests | Safety Engineer | Phase 1 |
| R4-SAFE-3 | HIGH | strobe/degradation branches remain non-functional | implement branch logic and cover in tests | Safety Engineer | Phase 1 |
| R4-INT-1 | HIGH | interpreter derives wrong base channel on sparse command maps | explicit channel-base contract and tests | Graph Runtime Engineer | Phase 1 |
| R4-RUN-1 | MEDIUM | fusion/midi no-op paths reduce determinism | implement deterministic transforms and tests | Input Pipeline Engineer | Phase 2 |
| R4-MAINT-1 | MEDIUM | deprecation drift in config/lint tooling | migrate config schemas and lock checks | Platform Engineer | Phase 3 |
| R4-TEST-1 | HIGH | no integration safety tests currently in `tests/integration` | add ordering and watchdog tests | QA Engineer | Phase 1 |

## 9) Re-Critique Protocol (Post-Fix, Mandatory)

After each phase:
1. Re-run all global and phase-specific verification commands.
2. Capture fresh diff evidence:
```bash
git diff --name-only
git diff --stat
```
3. Re-validate integration contracts touched by the phase (V105).
4. Run deterministic preflight and route checks against this plan:
```bash
python scripts/audit/plan_preflight.py --plan-file docs/round4_full_critique_implementation_plan.md --check integration --check routes
python scripts/audit/route_parity_check.py --plan-file docs/round4_full_critique_implementation_plan.md
```
5. Reconcile risk row updates with gate results (R1 row-level re-verification).
6. Perform full-plan stale-evidence sweep (R6/R12) before declaring GO.

## 10) Execution Checklist

1. Complete Phase 1 and pass G1-G5.
2. Complete Phase 2 and pass G1-G5.
3. Complete Phase 3 and pass G1-G5.
4. Run final full verification + preflight + route parity.
5. Capture final evidence snapshot and mark plan execution complete.
