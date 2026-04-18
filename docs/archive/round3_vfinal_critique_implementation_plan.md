# Round 3 vFinal Remediation Plan (Critique Framework)

## 0) Quick Summary

- Objective: convert the Round 3 vFinal backlog into a safety-first implementation plan aligned to `docs/reference/critique_implementation.md`.
- Primary outcome: eliminate unsafe DMX path risks and establish deterministic blackout behavior.
- Strategy: implement in three phases with hard STOP/GO gates and re-critique after each phase.
- Success condition: safety/output ordering proven by tests, interlock branches fully implemented, watchdog blackout path verified, and critical checks pass.

## 1) Required Inputs (V90)

| Input | Status | Evidence Anchor |
|---|---|---|
| Plan | Present | `docs/round3_vfinal_critique_implementation_plan.md` |
| Guide | Present | `docs/reference/critique_implementation.md` |
| Files | Present | `src/photonic_synesthesia/graph/builder.py`, `src/photonic_synesthesia/graph/nodes/safety_interlock.py`, `src/photonic_synesthesia/graph/nodes/dmx_output.py`, `src/photonic_synesthesia/interpreters/safety.py`, `src/photonic_synesthesia/core/state.py`, `src/photonic_synesthesia/core/config.py` |
| Functions | Present | `build_photonic_graph`, `SafetyInterlockNode.__call__`, `DMXOutputNode.__call__`, `DMXOutputNode.blackout`, `InterpreterNode.__call__` |
| Decisions | Present | Round 3 merged direction: safety-first sequencing, watchdog blackout, state split, property-based tests |
| Diffs | Pending | To be captured post-implementation via `git diff --name-only` and `git diff --stat` |

## 2) Scope and Ownership

| File | Role | Change Type |
|---|---|---|
| `src/photonic_synesthesia/graph/builder.py` | enforce safe execution order | update graph wiring |
| `src/photonic_synesthesia/graph/nodes/safety_interlock.py` | complete interlock logic + watchdog behavior | functional update |
| `src/photonic_synesthesia/graph/nodes/dmx_output.py` | consume only safety-validated frame path | contract update |
| `src/photonic_synesthesia/interpreters/safety.py` | shared safety constraints in pre-output path | constraint hardening |
| `src/photonic_synesthesia/core/state.py` | split/organize fast signal vs static config state fields | state model refactor |
| `src/photonic_synesthesia/core/config.py` | pydantic config modernization + tuning knobs | config update |
| `src/photonic_synesthesia/graph/nodes/feature_extract.py` | reduce hot-loop latency risk | performance refactor |
| `src/photonic_synesthesia/graph/nodes/midi_sense.py` | close TODO gaps for control signal quality | functional update |
| `src/photonic_synesthesia/graph/nodes/fusion.py` | remove no-op paths, deterministic behavior | functional update |
| `tests/unit/test_safety_interlock.py` | boundary and branch coverage for safety logic | expand tests |
| `tests/unit/test_interpreter_node.py` | invariants on safety constraints | expand tests |
| `tests/integration/test_output_safety_ordering.py` [NEW] | ordering proof: unsafe frame cannot transmit | new integration test |
| `tests/property/test_safety_invariants.py` [NEW] | property-based safety invariants | new property tests |

## 3) Top 10 Actions (Round 3 vFinal)

1. Fix safety/output ordering and data ownership in runtime path.
2. Implement missing interlock branches: strobe cooldown and graceful degradation.
3. Add independent watchdog blackout path with deterministic timeout behavior.
4. Consolidate blackout path into one atomic, reusable command surface.
5. Split runtime state into slower config state and fast signal/output state.
6. Add property-based invariants for DMX bounds and safety constraints.
7. Add end-to-end integration tests for ordering, failure, and blackout behavior.
8. Isolate heavy analysis work from output cadence to protect frame timing.
9. Refactor scene/fixture mapping toward typed profile-driven schema.
10. Modernize config and close known TODO/no-op technical debt.

## 4) Integration Contracts (V105)

### Contract A: Interpreter -> Safety -> Output

**Caller anchor:** `src/photonic_synesthesia/graph/builder.py`  
**Callee anchors:** `src/photonic_synesthesia/interpreters/safety.py`, `src/photonic_synesthesia/graph/nodes/safety_interlock.py`, `src/photonic_synesthesia/graph/nodes/dmx_output.py`

**Required composition rule:**
1. `InterpreterNode` produces constrained fixture commands.
2. `SafetyInterlockNode` performs final frame safety gate and blackout override logic.
3. `DMXOutputNode` transmits only the safety-approved frame.

**Failure mode to prevent:** DMX internal universe updated from unsafe commands before interlock gate.

**Verdict target:** PASS when ordering and ownership are enforced by code and integration tests.

### Contract B: Watchdog -> Blackout

**Caller anchor:** `src/photonic_synesthesia/graph/nodes/safety_interlock.py`  
**Callee anchor:** `src/photonic_synesthesia/graph/nodes/dmx_output.py:blackout`

**Required composition rule:**
- On heartbeat timeout or hard safety fault, watchdog path triggers blackout immediately and predictably.

**Failure mode to prevent:** stalled graph with continued unsafe/non-zero output.

**Verdict target:** PASS when timeout tests confirm blackout within configured threshold.

### Contract C: State Split and Node Read/Write Boundaries

**Caller anchors:** sensor/analysis/control nodes under `src/photonic_synesthesia/graph/nodes/`  
**Callee anchor:** `src/photonic_synesthesia/core/state.py`

**Required composition rule:**
- Static configuration values are not repeatedly validated/mutated in hot loop.
- Signal/output fields remain lightweight and deterministic for per-frame updates.

**Failure mode to prevent:** avoidable latency/jitter from heavyweight state handling.

**Verdict target:** PASS when state boundaries are explicit and validated by tests/lint/types.

## 5) Phased Implementation

### Phase 1: Safety Correctness (Must Pass First)

Scope: Actions 1-4, 7 (safety-critical subset), 10 (only safety-relevant TODOs)

Tasks:
- enforce safe order and output ownership path.
- complete strobe cooldown and graceful degradation branches.
- add independent watchdog-to-blackout behavior.
- add ordering and blackout integration tests.

Acceptance:
- unsafe frame cannot reach transmitter in tests.
- watchdog timeout causes blackout in deterministic test window.
- no unimplemented safety branches remain in active path.

### Phase 2: Runtime Reliability and Performance

Scope: Actions 5, 8, 10 (remaining technical debt)

Tasks:
- split state boundaries for hot path.
- isolate heavy feature extraction from output cadence.
- close TODO/no-op branches in fusion/midi paths that affect runtime decisions.

Acceptance:
- output cadence remains stable under analysis load in integration tests.
- state model changes pass mypy + pytest without regressions.

### Phase 3: Maintainability and Extensibility

Scope: Actions 6, 9

Tasks:
- add Hypothesis-based safety invariants.
- introduce typed fixture/profile mapping improvements while preserving compatibility.

Acceptance:
- property tests pass and catch invalid bound regressions.
- scene/fixture mapping logic is schema-driven and test-covered.

## 6) Verification Plan

Run after each phase:

```bash
pytest -q
pytest --cov=src/photonic_synesthesia --cov-report=term-missing -q
ruff check src tests
mypy src
```

Phase-specific checks:

```bash
# Safety ordering + blackout path
pytest -q tests/integration/test_output_safety_ordering.py

# Safety invariants
pytest -q tests/property/test_safety_invariants.py
```

Expected gate behavior:
- Phase 1: all safety tests PASS before proceeding.
- Phase 2: no regressions in safety gates plus runtime stability checks PASS.
- Phase 3: property tests and schema-driven mapping tests PASS.

## 7) Risk Register

| Risk ID | Severity | Description | Mitigation | Owner |
|---|---|---|---|---|
| R3-SAFE-1 | CRITICAL | unsafe frame may bypass interlock and transmit | enforce strict interpreter->safety->output contract + integration tests | runtime owner |
| R3-SAFE-2 | CRITICAL | watchdog does not blackout on hang | independent timeout path + deterministic tests | safety owner |
| R3-SAFE-3 | HIGH | missing strobe/degradation logic creates unsafe behavior under uncertainty | implement branches + boundary tests | safety owner |
| R3-RT-1 | HIGH | heavy analysis causes output jitter/frame overruns | isolate heavy work from output cadence | performance owner |
| R3-STATE-1 | MEDIUM | mixed config/signal state causes overhead and mutation risk | explicit state split and typed boundaries | architecture owner |
| R3-TEST-1 | HIGH | critical runtime path lacks sufficient invariant coverage | integration + property tests added and enforced | QA owner |

## 8) Decision Gates (STOP/GO)

| Gate | Condition | Fail Action |
|---|---|---|
| G1 | safe ordering/ownership proven by integration tests | STOP |
| G2 | watchdog blackout path proven by timeout test | STOP |
| G3 | no unimplemented safety branches in active path | STOP |
| G4 | phase verification commands pass (pytest, ruff, mypy) | STOP |
| G5 | safety-critical regressions absent after each phase | GO to next phase |

STOP/GO rule:
- Any FAIL in G1-G4 is STOP.
- GO requires all gates PASS for the current phase.

## 9) Post-Fix Re-Critique Protocol

After each phase:

1. Re-run verification commands in Section 6.
2. Capture updated diff evidence (`git diff --name-only`, `git diff --stat`).
3. Re-check Risk Register rows touched by the phase (row-level re-verification).
4. Reconcile Decision Gates with current evidence and update status.
5. Do not mark phase complete until gate evidence is current and consistent.

