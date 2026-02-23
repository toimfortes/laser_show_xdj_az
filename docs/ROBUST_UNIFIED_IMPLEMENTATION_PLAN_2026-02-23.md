# Robust Unified Implementation Plan (2026-02-23)

## 0) Scope and Intent

This plan consolidates all implementation-plan iterations created between 2026-02-19 and 2026-02-20:

- Root/docs plans:
  - `IMPLEMENTATION_PLAN.md`
  - `AUDIT_PLAN.md`
  - `PRODUCTION_PLAN.md`
  - `docs/implementation_plan_autonomous_solver_workflow.md`
  - `docs/round3_vfinal_critique_implementation_plan.md`
  - `docs/round4_full_critique_implementation_plan.md`
- Snapshot plans in `.ai_orchestrator/backups/state_2026-02-19T14-54-02.json` (`plans[]`, 15 entries).

Primary objective: ship a production-hardened, safety-first runtime for live DMX/laser use with deterministic behavior, auditable controls, and explicit operational gates.

## 1) Forensic Baseline (Repository Reality)

Date baseline captured: 2026-02-23.

### Confirmed implemented

- Safety ordering exists in graph wiring:
  - `src/photonic_synesthesia/graph/builder.py:229`
  - `src/photonic_synesthesia/graph/builder.py:232`
- Heartbeat watchdog is wired to DMX blackout callback:
  - `src/photonic_synesthesia/graph/nodes/safety_interlock.py:135`
  - `src/photonic_synesthesia/graph/nodes/safety_interlock.py:136`
- DMX output can use Art-Net transport with packet builder:
  - `src/photonic_synesthesia/graph/nodes/dmx_output.py:203`
  - `src/photonic_synesthesia/dmx/artnet.py:16`
- CLI run path has signal-aware shutdown and idempotent stop:
  - `src/photonic_synesthesia/ui/cli.py:79`
  - `src/photonic_synesthesia/ui/cli.py:103`

### Confirmed incomplete or placeholder

- Strobe cooldown branch is non-functional (`pass`):
  - `src/photonic_synesthesia/graph/nodes/safety_interlock.py:241`
- Low-beat-confidence graceful degradation branch is non-functional (`pass`):
  - `src/photonic_synesthesia/graph/nodes/safety_interlock.py:255`
- Fusion filter adaptation contains no-op branches (`pass`):
  - `src/photonic_synesthesia/graph/nodes/fusion.py:93`
  - `src/photonic_synesthesia/graph/nodes/fusion.py:96`
- MIDI EQ/effects are placeholder values:
  - `src/photonic_synesthesia/graph/nodes/midi_sense.py:166`
  - `src/photonic_synesthesia/graph/nodes/midi_sense.py:170`
- Web entrypoint is still explicitly unimplemented:
  - `src/photonic_synesthesia/ui/web_panel.py:9`
- Config style uses deprecated Pydantic v1-style inner `Config`:
  - `src/photonic_synesthesia/core/config.py:180`

### Snapshot-plan inconsistency resolved

Snapshot iterations include contradictory assumptions (repo-empty, read-failure, and fully-implemented claims). This plan is anchored only to current on-disk code and testable behavior.

## 2) Non-Negotiable Principles

1. No unsafe frame reaches output transport.
2. Every safety fallback is executable, not advisory.
3. Production process behavior must be observable without attaching debuggers.
4. Changes that alter cross-module boundaries require explicit contract validation.
5. No deployment recommendation without passing predefined STOP/GO gates.

## 3) Integration Contracts (V105)

### Integration Contract: Interpreter -> Safety Interlock -> DMX Commit

**Why this boundary exists:** enforce that fixture commands are constrained before any transmitter-owned universe mutation.

**Caller (anchor):** `src/photonic_synesthesia/graph/builder.py:229`  
**Callee (anchor):** `src/photonic_synesthesia/graph/nodes/safety_interlock.py:150`, `src/photonic_synesthesia/graph/nodes/dmx_output.py:244`

**Call expression (verbatim):**
```python
graph.add_edge("interpreter", "safety_interlock")
graph.add_edge("safety_interlock", "dmx_output")
```

**Callee signature (verbatim):**
```python
def __call__(self, state: PhotonicState) -> PhotonicState: ...
```

**Request/Source schema (verbatim, if applicable):**
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
| `state` | yes | graph runtime state | `PhotonicState` | `PhotonicState` | none | single mutable state object |
| `fixture_commands` | yes | `state["fixture_commands"]` | `list[FixtureCommand]` | consumed by safety+output | none | must be clamped before commit |
| `dmx_universe` | yes | `state["dmx_universe"]` | `bytes` | safety defense-in-depth input | `bytearray(...)` in node | prior-frame safeguard |

**Missing required inputs (if any):**
- none.

**Incompatible types (if any):**
- none expected.

**Return/Response contract (REQUIRED):**
- **Return value shape:** `PhotonicState`
- **Caller expects:** state updated with safe command/universe values and processing-times fields
- **Response model (if API):** not applicable
- **Mismatch?** CRITICAL if output commit happens before safety clamps

**Failure modes / status codes (REQUIRED for API boundaries):**
| Failure | Trigger | Where raised | HTTP code (if any) | Caller behavior |
|---|---|---|---|---|
| unsafe frame ownership | DMX node mutates private buffer before safety verdict | `src/photonic_synesthesia/graph/nodes/dmx_output.py` | n/a | STOP |
| partial safety application | only stale universe clamped, current commands not clamped | `src/photonic_synesthesia/graph/nodes/safety_interlock.py` | n/a | STOP |

**Verdict:** PASS (ordering is present), PARTIAL (incomplete safety branches).

---

### Integration Contract: Watchdog Timeout -> DMX Blackout Callback

**Why this boundary exists:** blackout must be triggered by an independent safety path when processing loop hangs.

**Caller (anchor):** `src/photonic_synesthesia/graph/nodes/safety_interlock.py:135`  
**Callee (anchor):** `src/photonic_synesthesia/graph/nodes/dmx_output.py:277`

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
| `on_timeout` | yes | `dmx_output.blackout` | `Callable[[], None]` | `Callable[[], None]` | none | must remain lock-safe and idempotent |
| `timeout_s` | yes | `self.config.heartbeat_timeout_s` | `float` | `float` | none | timeout policy input |

**Missing required inputs (if any):**
- none.

**Incompatible types (if any):**
- none.

**Return/Response contract (REQUIRED):**
- **Return value shape:** side effect only
- **Caller expects:** universe zeroization reaches transmitter-owned buffer
- **Response model (if API):** not applicable
- **Mismatch?** CRITICAL if timeout does not lead to blackout side effect

**Failure modes / status codes (REQUIRED for API boundaries):**
| Failure | Trigger | Where raised | HTTP code (if any) | Caller behavior |
|---|---|---|---|---|
| watchdog dead path | watchdog running but callback never invoked | `HeartbeatWatchdog._watchdog_loop` | n/a | STOP |
| non-idempotent blackout | repeated callbacks corrupt state | `DMXOutputNode.blackout` | n/a | STOP |

**Verdict:** PASS for wiring, needs soak validation under induced stalls.

---

### Integration Contract: DMX Universe Buffer -> Art-Net Packet Encoder

**Why this boundary exists:** incorrect packet mapping can transmit malformed network DMX frames.

**Caller (anchor):** `src/photonic_synesthesia/graph/nodes/dmx_output.py:208`  
**Callee (anchor):** `src/photonic_synesthesia/dmx/artnet.py:16`

**Call expression (verbatim):**
```python
self._artnet.send_dmx(
    universe=self._artnet_universe_address(),
    dmx_data=universe_data,
    sequence=self._artnet_sequence,
)
```

**Callee signature (verbatim):**
```python
def send_dmx(self, universe: int, dmx_data: bytes, sequence: int = 0) -> None: ...
```

**Request/Source schema (verbatim, if applicable):**
```python
_universe: bytearray  # start code + 512 channels
universe_data = extract_channel_payload(data)  # exactly channel payload
```

**Argument mapping + type chain (REQUIRED):**

| Arg | Required? | Source expression | Type@Source | Type@Callee | Conversion | Notes |
|---|---|---|---|---|---|---|
| `universe` | yes | `_artnet_universe_address()` | `int` | `int` | bit packing | must match Net/SubNet/Universe layout |
| `dmx_data` | yes | `extract_channel_payload(data)` | `bytes` | `bytes` | none | start code removed before ArtDmx |
| `sequence` | no | `_artnet_sequence` | `int` | `int` | modulo 256 | monotonically incrementing rollover |

**Missing required inputs (if any):**
- none.

**Incompatible types (if any):**
- none.

**Return/Response contract (REQUIRED):**
- **Return value shape:** side effect only (UDP send)
- **Caller expects:** packet serialized by `build_artdmx_packet`
- **Response model (if API):** not applicable
- **Mismatch?** CRITICAL if payload length or OpCode encoding is invalid

**Failure modes / status codes (REQUIRED for API boundaries):**
| Failure | Trigger | Where raised | HTTP code (if any) | Caller behavior |
|---|---|---|---|---|
| oversize payload | `len(dmx_data) > 512` | `build_artdmx_packet` | n/a | STOP and count error |
| closed socket | send while transmitter unopened | `ArtNetTransmitter.send_dmx` | n/a | STOP or fallback policy |

**Verdict:** PASS, retain strict packet tests and add protocol fixture assertions.

---

### Integration Contract: MIDI Callback Thread -> Runtime State Projection

**Why this boundary exists:** callback-thread state handoff must remain race-safe and deterministic.

**Caller (anchor):** `src/photonic_synesthesia/graph/nodes/midi_sense.py:131`  
**Callee (anchor):** `src/photonic_synesthesia/graph/nodes/midi_sense.py:145`

**Call expression (verbatim):**
```python
self._port = mido.open_input(port_name, callback=self._on_message)
```

**Callee signature (verbatim):**
```python
def __call__(self, state: PhotonicState) -> PhotonicState: ...
```

**Request/Source schema (verbatim, if applicable):**
```python
_message_queue: queue.Queue
state["midi_state"]: MidiState
```

**Argument mapping + type chain (REQUIRED):**

| Arg | Required? | Source expression | Type@Source | Type@Callee | Conversion | Notes |
|---|---|---|---|---|---|---|
| queued msg | yes | `_on_message -> _message_queue.put_nowait(msg)` | `mido.Message` | `_process_message(msg)` | none | callback thread to loop thread transfer |
| midi aggregate | yes | internal caches | `dict/list/float` | `MidiState` | normalization | must not block callback thread |

**Missing required inputs (if any):**
- none.

**Incompatible types (if any):**
- none.

**Return/Response contract (REQUIRED):**
- **Return value shape:** updated `PhotonicState` with `midi_state`
- **Caller expects:** deterministic projection with bounded queue drain
- **Response model (if API):** not applicable
- **Mismatch?** CRITICAL if callback path can deadlock frame loop

**Failure modes / status codes (REQUIRED for API boundaries):**
| Failure | Trigger | Where raised | HTTP code (if any) | Caller behavior |
|---|---|---|---|---|
| queue overflow drops excessive control data | callback producer outruns consumer | `_on_message` | n/a | WARN + metric |
| stale defaults persist | placeholders never replaced by real EQ/effects | `__call__` state projection | n/a | FAIL Phase 2 gate |

**Verdict:** PARTIAL (threading pattern is sound; state fidelity is incomplete).

---

### Integration Contract: Settings YAML Loader -> Runtime Settings Model

**Why this boundary exists:** startup must fail-closed on invalid safety and fixture configuration.

**Caller (anchor):** `src/photonic_synesthesia/ui/cli.py:66`  
**Callee (anchor):** `src/photonic_synesthesia/core/config.py:185`

**Call expression (verbatim):**
```python
settings = Settings.from_yaml(ctx.obj["config_path"])
```

**Callee signature (verbatim):**
```python
@classmethod
def from_yaml(cls, path: Path) -> Settings: ...
```

**Request/Source schema (verbatim, if applicable):**
```python
YAML -> dict -> Settings(**data)
```

**Argument mapping + type chain (REQUIRED):**

| Arg | Required? | Source expression | Type@Source | Type@Callee | Conversion | Notes |
|---|---|---|---|---|---|---|
| `path` | yes | click `--config` path | `Path` | `Path` | none | CLI-validated path exists |
| `data` | yes | `yaml.safe_load(f)` | `dict[str, Any]` | `Settings` ctor | Pydantic validation | should reject invalid ranges/types |

**Missing required inputs (if any):**
- none.

**Incompatible types (if any):**
- none.

**Return/Response contract (REQUIRED):**
- **Return value shape:** fully validated `Settings`
- **Caller expects:** safe defaults only when explicit values absent
- **Response model (if API):** not applicable
- **Mismatch?** CRITICAL if unsafe values bypass validation

**Failure modes / status codes (REQUIRED for API boundaries):**
| Failure | Trigger | Where raised | HTTP code (if any) | Caller behavior |
|---|---|---|---|---|
| malformed config accepted | weak validation/model config drift | `Settings` model parse | n/a | STOP startup |
| silent fallback masks bad deployment | broad exception swallowing in CLI path | `ui/cli.py` | n/a | FAIL gate, improve diagnostics |

**Verdict:** PARTIAL (functional, needs stricter model and startup validation behavior).

## 4) Route Reality (V106)

This plan intentionally defines no concrete HTTP URL path commitments because the web panel server module is currently absent (`src/photonic_synesthesia/ui/web_panel.py:9`).

All future endpoint work in this plan uses symbolic identifiers until a concrete server file exists:

- `ROUTE_STATUS`
- `ROUTE_EVENTS`
- `ROUTE_METRICS`
- `WS_DASHBOARD`

Once implemented, endpoint parity check is mandatory before release.

## 5) Phased Implementation Plan

### Phase 1: Safety Completeness and Determinism (Blocking)

Scope:

- `src/photonic_synesthesia/graph/nodes/safety_interlock.py`
- `tests/unit/test_safety_interlock.py`
- `tests/unit/test_production_hardening.py`
- new integration tests for timeout and blackout determinism

Tasks:

1. Replace strobe cooldown `pass` branch with executable suppression logic.
2. Replace low-confidence graceful-degradation `pass` branch with deterministic dimmer scaling strategy.
3. Add explicit cooldown state transitions and timing tests.
4. Add deterministic timeout-to-blackout integration test with bounded tolerance.

Acceptance criteria:

- No runtime `pass` remains in active safety branches.
- Timeout path blackouts occur within configured watchdog envelope in tests.
- Safety tests pass with branch coverage for cooldown and degradation conditions.

STOP conditions:

- Any test demonstrates non-zero output after triggered emergency blackout.

### Phase 2: Input Fidelity and Fusion Completion (High)

Scope:

- `src/photonic_synesthesia/graph/nodes/midi_sense.py`
- `src/photonic_synesthesia/graph/nodes/fusion.py`
- related unit tests

Tasks:

1. Implement EQ tracking map for `eq_positions` instead of fixed 0.5 defaults.
2. Implement effects state detection pipeline for `active_effects`.
3. Replace fusion filter no-op branches with deterministic intensity modifiers.
4. Add regression tests validating filter-to-lighting behavior.

Acceptance criteria:

- No placeholder defaults in production MIDI projection for tracked controls.
- Fusion output changes measurably and deterministically with filter position extremes.

STOP conditions:

- Fusion or MIDI changes introduce non-deterministic output in repeated mock runs.

### Phase 3: Config Hardening and Startup Validation (High)

Scope:

- `src/photonic_synesthesia/core/config.py`
- `src/photonic_synesthesia/ui/cli.py`
- `config/default.yaml`
- startup tests

Tasks:

1. Migrate settings model configuration from inner `Config` to `model_config = SettingsConfigDict(...)`.
2. Enforce stricter field constraints for safety-critical numeric ranges.
3. Add startup config validation command path that fails before graph start when scene/fixture requirements are missing.
4. Add explicit diagnostics for invalid fixture profile references and malformed scene files.

Acceptance criteria:

- Invalid configuration exits before starting sensor/output threads.
- Pydantic v2-compatible config style is used consistently.

STOP conditions:

- Any malformed safety config still allows runtime start.

### Phase 4: Observability and Operations Hardening (High)

Scope:

- logging setup in `src/photonic_synesthesia/ui/cli.py`
- runtime stats surfaces from graph and nodes
- deployment unit files/docs (new)

Tasks:

1. Standardize JSON structured logs for run-loop, safety transitions, and output health.
2. Expose process and node metrics through Prometheus integration.
3. Add service runtime profile and operational restart policy docs.
4. Add fail-safe watchdog/health signal checks for production deployment.

Acceptance criteria:

- Operator can diagnose output stalls, sensor dropouts, and safety trips from logs/metrics alone.
- Metrics export validated in tests/smoke checks.

STOP conditions:

- Missing visibility for blackout cause attribution.

### Phase 5: Web Panel Foundation (Medium)

Scope:

- `src/photonic_synesthesia/ui/web_panel.py`
- new server module under `src/photonic_synesthesia/ui/`
- tests for HTTP+WebSocket behavior

Tasks:

1. Replace web-panel fail-fast stub with minimal FastAPI app factory.
2. Implement symbolic routes (`ROUTE_STATUS`, `ROUTE_EVENTS`, `ROUTE_METRICS`) and one dashboard websocket channel (`WS_DASHBOARD`).
3. Add route-parity validation script target once paths are committed.

Acceptance criteria:

- `photonic-web` starts and serves health/status + live stream surface.
- Endpoint and websocket tests pass.

STOP conditions:

- Unauthenticated control-plane actions exposed by default.

## 6) Verification Matrix and Gates

### Global commands (every phase)

```bash
ruff check src tests
mypy src
pytest -q
```

### Contract and parity validators

```bash
python scripts/audit/plan_preflight.py --plan-file docs/ROBUST_UNIFIED_IMPLEMENTATION_PLAN_2026-02-23.md --check integration --check routes
python scripts/audit/route_parity_check.py --plan-file docs/ROBUST_UNIFIED_IMPLEMENTATION_PLAN_2026-02-23.md
```

### Additional phase checks

```bash
# Safety timeout and blackout behavior
pytest -q tests/unit/test_safety_interlock.py tests/unit/test_production_hardening.py

# Art-Net packet invariants
pytest -q tests/unit/test_artnet.py tests/unit/test_dmx_universe_contract.py
```

Gate policy:

- G1: lint+types pass
- G2: critical safety tests pass
- G3: integration contracts remain valid
- G4: no unresolved TODO/pass placeholders in active runtime paths
- G5: phase-specific acceptance criteria met

Proceed only on PASS for G1-G5.

## 7) Research-Backed Decisions

### Protocol and runtime

1. Preserve strict Art-Net packet semantics in serializer tests:
   - OpCode for ArtDmx is defined as `0x5000`.
   - Port-Address is 15-bit Net+Sub-Net+Universe.
   - ArtDmx length should be even and in valid range.
2. Keep StateGraph-centric architecture and explicit compile step; LangGraph runtime model uses BSP-like super-steps and compiled runtime semantics.

### Threading and sensor I/O

1. Keep callback-based audio capture with bounded processing in callback context and device discovery through `query_devices` patterns.
2. Keep MIDI callback ingestion through queue boundary; callback is documented as running on a different thread and requiring synchronization precautions.
3. Keep MSS-based screen capture object reuse in long-running loops; docs recommend reusing one instance and describe thread-safe behavior with serialized grabs.
4. Keep OpenCV template matching pipeline for deterministic OCR fallback and match scoring.

### Config and platform hardening

1. Move to Pydantic v2 `model_config` pattern; nested `Config` class is deprecated.
2. Migrate Ruff config to explicit `tool.ruff.lint` sectioning.
3. Service hardening profile should include `ProtectSystem`, `ProtectHome`, `PrivateTmp`, `NoNewPrivileges`, and bounded capabilities.
4. Add Prometheus export path using official client helpers (`start_http_server` for side-thread export or ASGI mount in web mode).

### Laser compliance and operating constraints

1. Keep compliance checklist for US operations: FDA references show Class IIIb/IV light show use requires specific variance/report submissions before operation.
2. Keep explicit operator warning and deployment checklist for legal/safety readiness.

### Device references

1. XDJ-AZ software support pages indicate MIDI message list availability and firmware/driver update expectations; preserve update verification in runbook.

## 8) Risk Register

| Risk | Severity | Likelihood | Mitigation | Exit Criteria |
|---|---|---|---|---|
| Hidden unsafe output edge case | Critical | Medium | expand property/integration safety tests | repeated randomized safety tests pass |
| Input thread contention | High | Medium | queue metrics, lock audits, bounded callback work | no dropped-message burst under stress target |
| Config drift across environments | High | Medium | strict startup validation and schema constraints | invalid config fails fast in CI smoke |
| Operational blind spots | High | Medium | structured logs + metrics + restart policy | incident triage without reproducer shell access |
| Regulatory misuse in live context | Critical | Low-Med | compliance checklist + explicit docs | operator sign-off checklist complete |

## 9) Single-Fixture Constraint (AliExpress Unit Only)

Constraint:

- Deployment hardware is one light fixture only (AliExpress listing provided by operator).
- All runtime and testing scopes must assume exactly one physical output device until hardware inventory changes.

Current classification lock (2026-02-23):

- Fixture is treated as DMX-capable OEM 4-lens RGBY laser.
- Primary runtime profile: 7-channel layout.
- Fallback profile retained for field verification: 9-channel variant.
- DIP requirement for DMX mode: switch #10 ON; switches #1-#9 encode start address.

Pre-Phase Gate (required before Phase 1 implementation work):

1. Classify fixture control interface:
   - DMX512 capable (explicit channel map/manual present), or
   - non-DMX consumer light (mains-only, RF remote, BLE-only, etc.).
2. Capture fixture evidence artifact:
   - photo of rear label and DIP/menu settings,
   - manual/spec page with channel map,
   - confirmed mode selected on hardware during tests.
3. Record fixture profile decision:
   - use `config/fixtures/laser_generic_7ch.yaml` as primary,
   - if field behavior contradicts 7CH map, switch to `config/fixtures/laser_generic_9ch.yaml`.

Locked 7CH channel contract:

1. CH1 control mode (`200-255` = manual DMX).
2. CH2 pattern select.
3. CH3 X position.
4. CH4 Y position (safety-clamped).
5. CH5 scan speed (safety lower-bound enforced until polarity verification complete).
6. CH6 pattern play speed.
7. CH7 zoom.

Single-fixture operating rules (DMX branch):

1. Exactly one fixture entry in runtime config.
2. Universe writes outside fixture address span are treated as defect.
3. Scene engine must produce single-fixture-safe outputs only (no moving-head/panel assumptions).
4. Safety clamps remain enforced even when fixture reports internal auto/sound-active modes.

Single-fixture operating rules (non-DMX branch):

1. Do not route output through DMX runtime as if fine-grained channel control exists.
2. Restrict to analysis-only mode or explicit coarse on/off switching path with separate risk review.
3. Mark laser-specific claims as not applicable until hardware capability is confirmed.

Additional acceptance criteria (all phases):

- `fixtures` length is 1 in active deployment config.
- At least one integration test asserts no channel writes occur outside configured fixture span.
- Operator runbook explicitly documents exact fixture mode and wiring for repeatability.

## 10) Execution Checklist

- [ ] Phase 1 complete and G1-G5 pass.
- [ ] Phase 2 complete and G1-G5 pass.
- [ ] Phase 3 complete and G1-G5 pass.
- [ ] Phase 4 complete and G1-G5 pass.
- [ ] Phase 5 complete and G1-G5 pass.
- [ ] Single-fixture pre-phase gate complete (DMX vs non-DMX branch locked).
- [ ] Post-fix re-critique run and archived.

## 11) Post-Fix Re-Critique Protocol

After each merged correction set:

1. Build delta list of all changed claims (contracts, safety behavior, runtime interfaces, route declarations).
2. Re-run integration contract validation (V105) for all touched boundaries.
3. Re-run route parity validation (V106) for any added server routes.
4. Re-run global and phase-specific verification matrix.
5. Append a dated addendum section to this plan with PASS/FAIL and unresolved items.

No phase is considered complete until re-critique passes.

## 12) Sources (Primary References)

- LangGraph overview: https://docs.langchain.com/oss/python/langgraph/overview
- LangGraph Graph API: https://docs.langchain.com/oss/python/langgraph/graph-api
- LangGraph runtime (Pregel): https://docs.langchain.com/oss/python/langgraph/pregel
- Art-Net 4 specification (official PDF): https://art-net.org.uk/downloads/art-net.pdf
- Art-Net specification page: https://art-net.org.uk/art-net-specification/
- PyFtdi UART backend usage: https://eblot.github.io/pyftdi/api/uart.html
- PyFtdi URL scheme: https://eblot.github.io/pyftdi/urlscheme.html
- python-sounddevice API: https://python-sounddevice.readthedocs.io/en/0.3.12/api.html
- Mido ports/callback threading: https://mido.readthedocs.io/en/latest/ports/
- Python MSS usage and multithreading: https://python-mss.readthedocs.io/usage.html
- Python MSS examples: https://python-mss.readthedocs.io/en/latest/examples.html
- OpenCV template matching: https://docs.opencv.org/4.x/de/da9/tutorial_template_matching.html
- Pydantic v2 migration guide: https://docs.pydantic.dev/2.0/migration/
- Pydantic settings API: https://docs.pydantic.dev/latest/api/pydantic_settings/
- Ruff configuration docs: https://docs.astral.sh/ruff/configuration/
- Prometheus Python client exporting: https://prometheus.github.io/client_python/exporting/http/
- Prometheus FastAPI+Gunicorn pattern: https://prometheus.github.io/client_python/exporting/http/fastapi-gunicorn/
- systemd exec sandboxing controls: https://www.freedesktop.org/software/systemd/man/254/systemd.exec.html
- FDA laser light show requirements: https://www.fda.gov/radiation-emitting-products/home-business-and-entertainment-products/laser-light-shows
- FDA laser notice on IIIb/IV variance responsibilities: https://www.fda.gov/regulatory-information/search-fda-guidance-documents/responsibilities-laser-light-show-projector-manufacturers-dealers-and-distributors-laser-notice-51
- XDJ-AZ software information (MIDI messaging context): https://www.pioneerdj.com/en/support/software-information/all-in-one-system/xdj-az/
