# Free-Flow Dramaturgy Plan (Planning Only)

Date: 2026-02-23  
Scope: Convert current reactive behavior into a musical dramaturgy show engine.  
Constraint: Planning only. No production code changes in this plan.

## Objectives

- Move from continuous modulation to intentional moments and contrast.
- Enforce phrase-aware transitions (8/16/32-bar boundaries).
- Introduce role-specific laser behavior (low/mid/high) with explicit band and envelope separation.
- Preserve fail-closed safety ordering (`interpreter -> safety_interlock -> dmx_output`).
- Add sync resilience (dynamic tempo drift handling + external sync arbitration).
- Validate with measurable acceptance criteria before implementation.

## Free-Flow Workstreams

### A. Dramaturgy Core

Target files:
- `src/photonic_synesthesia/core/state.py`
- `src/photonic_synesthesia/director/engine.py`
- `src/photonic_synesthesia/graph/nodes/director_intent.py`

Plan:
- Add `ShowState` enum: `void`, `tension`, `lift`, `impact`, `afterglow`.
- Extend director intent with:
  - `show_state`
  - `darkness_reserve`
  - `macro_armed`
  - `next_transition_bar`
  - `key_moment_id` (nullable)
- Add `Key Moment Registry` policy:
  - Reserve max 5 key moments per session.
  - `impact`-class looks are exclusive to registered moment windows.
  - Non-key-moment passages capped at `lift` equivalent output ceiling.

Acceptance:
- Director outputs stable states for at least one phrase unless macro override is armed.
- Illegal state jumps are blocked (`void -> impact` without `tension|lift` unless emergency accent path).
- Peak dilution index (Tier-4-like cues outside key windows) is within target bound.

### B. Phrase Clock and Musical Timing

Target files:
- `src/photonic_synesthesia/graph/nodes/beat_track.py`
- `src/photonic_synesthesia/core/state.py`
- `src/photonic_synesthesia/director/engine.py`

Plan:
- Add phrase clock fields:
  - `bar_count_total`
  - `bar_in_phrase`
  - `phrase_len_bars`
  - `is_phrase_boundary`
  - `phase_error_ms`
- Use a PLL-style continuous correction path to avoid drift-then-snap behavior.
- Add inertial clock mode for low-confidence windows (continue with last trusted phase/BPM until re-lock).
- Transition legality rule:
  - Requests arriving after the configured arm deadline in a gate are held to the next same-length gate.
  - Competing requests in same gate resolve by priority: `safety blackout > operator override > AI dramaturgy > autoloop suggestion`.
  - Phrase-gate legality never delays safety actions; safety faults can preempt immediately.
- Autoloop quantization rule:
  - Legal loop lengths are `{2, 4, 8, 16}` bars.
  - Non-legal proposals are rounded down to nearest legal value.

Acceptance:
- >= 90% major state transitions occur on configured phrase boundaries in simulated mixes.
- Phrase counter re-locks within 2 bars after controlled tempo shift events.
- Late requests are held (not dropped, not fired mid-phrase).

### C. Darkness Budget and Contrast

Target files:
- `src/photonic_synesthesia/director/engine.py`
- `src/photonic_synesthesia/graph/nodes/scene_select.py`
- `src/photonic_synesthesia/graph/nodes/fixture_control.py`

Plan:
- Add rolling one-minute output budget model.
- Enforce target low-output share: 35-60% per minute.
- Add hard restraint rules:
  - Minimum pre-impact low-output window.
  - Mandatory post-impact decompression window before next high-intensity state.
- Enforce budget-aware suppression:
  - If reserve is depleted, deny new impact requests and route to `void|afterglow`.

Acceptance:
- In stress simulation, low-output ratio remains within 0.35-0.60 over rolling 60s windows.
- Back-to-back impact macros are rejected until budget recovers.
- Darkness ratio and peak-dilution metrics are recorded per run.

### D. Laser Role Separation

Target files:
- `src/photonic_synesthesia/graph/nodes/fixture_control.py`
- `config/fixtures/*.yaml` (role metadata)

Plan:
- Assign each laser fixture a role with explicit spectral/temporal contract:
  - `laser_low`: `<180 Hz`, slower envelopes, fall smoothing for stable bass motion.
  - `laser_mid`: `180-2500 Hz`, groove-linked geometry/chase.
  - `laser_high`: `>2500 Hz`, fast attack/release transient accents, low duty cycle.
- Apply separate gain/attack/release/fall controls per role to avoid uniform movement.
- Require role profile metadata for every laser fixture entry.

Acceptance:
- Same audio frame produces distinct outputs per role (non-identical channel trajectories).
- Role contracts remain stable across scene changes.
- Spectral isolation and response-time bounds are testable and tracked.

### E. Moment Macros

Target files:
- `src/photonic_synesthesia/director/engine.py`
- `src/photonic_synesthesia/graph/nodes/scene_select.py`

Plan:
- Add macro primitives:
  - `pre_drop_silence` (1-2 bars)
  - `drop_impact` (short, high-contrast punch)
  - `opus_tail` (long decay/release)
- Macros are queued and applied at phrase boundaries by default.
- Emergency accent policy:
  - May bypass phrase boundary only.
  - Must still traverse `interpreter -> safety_interlock -> dmx_output`.
  - Denied when safety state is stale/invalid or watchdog-failed.
- Add cooldown + lockout rules with explicit bar-based timers.

Acceptance:
- Macro cooldown and lockout rules prevent repetitive trigger spam.
- `drop_impact` cannot fire twice within configured cooldown bars.
- At most one transition/macro commit per phrase gate open.

### F. Safety and Output Guarantees

Target files:
- `src/photonic_synesthesia/graph/builder.py`
- `src/photonic_synesthesia/graph/nodes/interpreter.py`
- `src/photonic_synesthesia/graph/nodes/safety_interlock.py`
- `src/photonic_synesthesia/graph/nodes/dmx_output.py`

Plan:
- Preserve and verify ordering:
  - `interpreter -> safety_interlock -> dmx_output`
- Ensure macro and role logic cannot bypass safety clamps.
- Treat low beat-confidence and watchdog events as explicit conservative fallbacks.
- Use atomic safety commit semantics (`last_valid_state` latch) to avoid transient DMX leakage during rapid transition churn.

Fail-closed invariants:
- `safety_interlock` is the only authority that can permit laser emission.
- Any fault (watchdog timeout, invalid safety fields, out-of-envelope command, scan-fail) triggers blackout.
- Safety clamps/blackout are immediate and not phrase-gated.
- Blackout is latched until explicit operator reset.
- No graph path may route around `safety_interlock` to write DMX.

Acceptance:
- Safety interlock can force blackout from any show state.
- No unsafe command reaches DMX output during induced fault tests.
- Blackout on watchdog/fault occurs within one frame budget and remains latched.

### G. External Sync and Trigger Interop

Target files:
- `src/photonic_synesthesia/graph/nodes/beat_track.py`
- `src/photonic_synesthesia/graph/nodes/fusion.py`
- `src/photonic_synesthesia/core/state.py`

Plan:
- Add sync arbiter policy:
  - Priority order: `timecode > link > midi_clock > internal_beat > manual_tap`.
- Add sync state fields:
  - `sync_source`
  - `clock_inertia_active`
  - `phase_error_ms`
  - `external_event_trigger` (optional)
- Add fallback handover behavior:
  - Source loss should soft-handover without resetting phrase counters.
  - Arbiter timeout must deterministically fall back to local phrase clock authority to prevent sync deadlock.

Acceptance:
- Source handover preserves phrase continuity and avoids scene reset.
- Phase error remains below target bound under controlled drift tests.

### H. Audience-Scanning Constraints (ILDA Framing)

Target files:
- `src/photonic_synesthesia/graph/nodes/safety_interlock.py`
- `src/photonic_synesthesia/core/config.py`

Plan:
- Audience scanning disabled by default (`audience_scan_enabled=false`).
- Enforce audience exclusion zones/horizon masks as hard no-output regions when audience scan is disabled.
- Enforce scan-fail and dwell/static-beam constraints in safety layer.
- Any audience-zone violation or scan-fail triggers latched blackout before transport.

Acceptance:
- With audience scanning disabled, no audience-zone intersections are allowed.
- Scan-fail/dwell violations trigger latched blackout and require explicit operator reset.

## Integration Contracts (Plan-Level)

### Integration Contract: Beat Track -> Director

**Why this boundary exists:** phrase-safe dramaturgy requires reliable beat/phrase/sync primitives entering director policy.

**Caller (anchor):** `src/photonic_synesthesia/graph/nodes/beat_track.py`  
**Callee (anchor):** `src/photonic_synesthesia/director/engine.py`

**Call expression (verbatim):**
```python
decision = self.engine.decide(state)
```

**Callee signature (verbatim):**
```python
def decide(self, state: PhotonicState) -> DirectorDecision:
```

**Request/Source schema (verbatim, if applicable):**
```python
state["beat_info"] = {
  "bpm": float,
  "bar_position": int,
  "downbeat": bool,
  "confidence": float,
}
state["phase_error_ms"]: float
state["sync_source"]: str
state["clock_inertia_active"]: bool
```

**Argument mapping + type chain (REQUIRED):**

| Arg | Required? | Source expression | Type@Source | Type@Callee | Conversion | Notes |
|---|---|---|---|---|---|---|
| `state` | yes | graph runtime state | `PhotonicState` | `PhotonicState` | none | includes planned phrase + sync fields |

**Missing required inputs (if any):**
- none after planned fields are added.

**Incompatible types (if any):**
- none expected.

**Return/Response contract (REQUIRED):**
- **Return value shape:** `DirectorDecision`
- **Caller expects:** `director_state` fields emitted via `DirectorIntentNode`
- **Mismatch?** CRITICAL if phrase gating / sync confidence flags are absent.

**Failure modes / status codes (REQUIRED for API boundaries):**
| Failure | Trigger | Where raised | HTTP code (if any) | Caller behavior |
|---|---|---|---|---|
| phrase drift | tempo shifts without controlled re-lock | `beat_track.py` | n/a | hold/soft-correct scene timing |
| low confidence | confidence below threshold | `engine.py` | n/a | force conservative state |

**Verdict:** PASS with planned phrase/sync schema extension.

### Integration Contract: Director -> Scene Select

**Why this boundary exists:** director intent must translate into controlled scene transitions without violating phrase policy.

**Caller (anchor):** `src/photonic_synesthesia/graph/nodes/director_intent.py`  
**Callee (anchor):** `src/photonic_synesthesia/graph/nodes/scene_select.py`

**Call expression (verbatim):**
```python
state["director_state"] = DirectorState(...)
```

**Callee signature (verbatim):**
```python
def __call__(self, state: PhotonicState) -> PhotonicState:
```

**Request/Source schema (verbatim, if applicable):**
```python
DirectorState = {
  "target_scene": str,
  "allow_scene_transition": bool,
  "show_state": str,
  "darkness_reserve": float,
  "macro_armed": bool,
}
```

**Argument mapping + type chain (REQUIRED):**

| Arg | Required? | Source expression | Type@Source | Type@Callee | Conversion | Notes |
|---|---|---|---|---|---|---|
| `target_scene` | yes | `state["director_state"]["target_scene"]` | `str` | `str` | none | planned show-state-aware mapping |
| `allow_scene_transition` | yes | `state["director_state"]["allow_scene_transition"]` | `bool` | `bool` | none | phrase gate authority |
| `macro_armed` | yes | `state["director_state"]["macro_armed"]` | `bool` | `bool` | none | macro activation policy |

**Missing required inputs (if any):**
- concrete macro queue structure must be defined before implementation.

**Incompatible types (if any):**
- none expected.

**Return/Response contract (REQUIRED):**
- **Return value shape:** updated `state["scene_state"]`
- **Caller expects:** deterministic pending/current scene handling
- **Mismatch?** CRITICAL if transition bypasses boundary rules.

**Failure modes / status codes (REQUIRED for API boundaries):**
| Failure | Trigger | Where raised | HTTP code (if any) | Caller behavior |
|---|---|---|---|---|
| invalid scene key | target scene missing from loaded scenes | `scene_select.py` | n/a | fallback to safe scene |
| transition spam | repeated scene swaps intra-phrase | `scene_select.py` | n/a | deny transition |

**Verdict:** PASS with macro queue definition follow-up.

### Integration Contract: Scene Select -> Fixture Control

**Why this boundary exists:** selected scene/state must fan out into role-aware fixture commands with darkness scaling.

**Caller (anchor):** `src/photonic_synesthesia/graph/nodes/scene_select.py`  
**Callee (anchor):** `src/photonic_synesthesia/graph/nodes/fixture_control.py`

**Call expression (verbatim):**
```python
graph.add_edge("scene_select", "laser_control")
graph.add_edge("laser_control", "moving_head_control")
graph.add_edge("moving_head_control", "panel_control")
```

**Callee signature (verbatim):**
```python
def __call__(self, state: PhotonicState) -> PhotonicState:
```

**Request/Source schema (verbatim, if applicable):**
```python
state["scene_state"]["current_scene"]: str
state["audio_features"]: AudioFeatures
state["beat_info"]: BeatInfo
state["director_state"]["darkness_reserve"]: float
```

**Argument mapping + type chain (REQUIRED):**

| Arg | Required? | Source expression | Type@Source | Type@Callee | Conversion | Notes |
|---|---|---|---|---|---|---|
| `current_scene` | yes | `state["scene_state"]["current_scene"]` | `str` | `str` | none | scene semantics source |
| `audio_features` | yes | `state["audio_features"]` | `AudioFeatures` | `AudioFeatures` | none | role band drivers |
| `beat_info` | yes | `state["beat_info"]` | `BeatInfo` | `BeatInfo` | none | phrase/beat sync |
| `darkness_reserve` | yes | `state["director_state"]["darkness_reserve"]` | `float` | `float` | none | intensity suppression budget |

**Missing required inputs (if any):**
- role assignments per fixture in config (planned addition).

**Incompatible types (if any):**
- none expected.

**Return/Response contract (REQUIRED):**
- **Return value shape:** `state["fixture_commands"]` appended with per-fixture values
- **Caller expects:** non-uniform role outputs and darkness-scaled intensities
- **Mismatch?** CRITICAL if all roles collapse to identical behavior.

**Failure modes / status codes (REQUIRED for API boundaries):**
| Failure | Trigger | Where raised | HTTP code (if any) | Caller behavior |
|---|---|---|---|---|
| role collision | high-role profile applied to low-role fixture | `fixture_control.py` | n/a | reject fixture command set |
| budget bypass | impact intensities emitted when reserve is empty | `fixture_control.py` | n/a | clamp to safe low-output mode |

**Verdict:** PASS with role metadata contract.

### Integration Contract: Interpreter -> Safety -> DMX

**Why this boundary exists:** no command may reach transport without final safety validation.

**Caller (anchor):** `src/photonic_synesthesia/graph/nodes/interpreter.py`  
**Callee (anchor):** `src/photonic_synesthesia/graph/nodes/safety_interlock.py` and `src/photonic_synesthesia/graph/nodes/dmx_output.py`

**Call expression (verbatim):**
```python
graph.add_edge("interpreter", "safety_interlock")
graph.add_edge("safety_interlock", "dmx_output")
```

**Callee signature (verbatim):**
```python
def __call__(self, state: PhotonicState) -> PhotonicState:
```

**Request/Source schema (verbatim, if applicable):**
```python
state["fixture_commands"]: list[FixtureCommand]
state["safety_state"]: SafetyState
state["dmx_universe"]: bytes
```

**Argument mapping + type chain (REQUIRED):**

| Arg | Required? | Source expression | Type@Source | Type@Callee | Conversion | Notes |
|---|---|---|---|---|---|---|
| `fixture_commands` | yes | `state["fixture_commands"]` | `list[FixtureCommand]` | `list[FixtureCommand]` | none | must be clamped/denied when unsafe |
| `safety_state` | yes | `state["safety_state"]` | `SafetyState` | `SafetyState` | none | emergency and watchdog authority |
| `dmx_universe` | yes | `state["dmx_universe"]` | `bytes` | `bytes/bytearray` | internal buffer handling | output payload source |

**Missing required inputs (if any):**
- none.

**Incompatible types (if any):**
- none expected.

**Return/Response contract (REQUIRED):**
- **Return value shape:** safe `PhotonicState` suitable for transport
- **Caller expects:** deterministic blackout on unsafe conditions
- **Mismatch?** CRITICAL if safety can be bypassed by macro path.

**Failure modes / status codes (REQUIRED for API boundaries):**
| Failure | Trigger | Where raised | HTTP code (if any) | Caller behavior |
|---|---|---|---|---|
| watchdog timeout | stale heartbeat | `safety_interlock.py` | n/a | force latched blackout |
| unsafe beam envelope | command exceeds safe envelope | `safety_interlock.py` | n/a | clamp/disable output |

**Verdict:** PASS; keep ordering immutable.

## Validation Gates (Before Any Implementation)

1. Design Gate:
- Finalize schema changes in `PhotonicState` and `DirectorState`.
- Confirm no field name/type conflicts with existing nodes.
- Define macro queue structure and sync arbiter fields.

2. Contract Gate:
- Verify all integration contracts with concrete field mapping tables.
- Confirm no transition path bypasses safety.

3. Test Gate:
- Define tests first in `tests/unit` and `tests/integration`:
  - phrase-boundary transition tests
  - late-arriving-request hold tests
  - competing request priority tests
  - autoloop quantization tests
  - darkness budget compliance tests
  - macro cooldown tests
  - spectral isolation and envelope response tests
  - sync handover / drift correction tests
  - sync-arbiter timeout fallback tests
  - safety forced-blackout and latch tests
  - safety-preempts-phrase-gate tests
  - no-transient-DMX-leakage tests during rapid scene/macro transitions

4. Production Readiness Gate:
- Establish stop/go thresholds:
  - phrase alignment >= 90%
  - darkness budget compliance in target range
  - sync phase error within configured bound under drift
  - safety blackout latency within accepted bound

## Risks and Controls

- Risk: Overfitting dramaturgy to a single genre.
  - Control: scene/phrase policy profiles per style.
- Risk: Macro overuse reduces contrast.
  - Control: cooldown bars + darkness reserve checks + key moment exclusivity.
- Risk: Tempo drift causes late transitions.
  - Control: PLL correction + inertial mode + sync arbiter handover policy.
- Risk: New logic introduces safety regression.
  - Control: preserve fail-closed ordering and add explicit latch tests.

## Explicit Non-Goals (This Document)

- No code implementation.
- No fixture patch rewrites.
- No transport/protocol migration.
