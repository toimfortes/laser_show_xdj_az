# Photonic Synesthesia: Codebase Deep Dive + Deep-Research Handoff

## 1) How This Codebase Works (Detailed)

### 1.1 High-level purpose
This project is a real-time lighting controller that turns music/DJ context into DMX output. It is built as a state-machine graph where each node reads/writes a shared typed state object.

Core path:
1. Sense audio/MIDI/CV
2. Extract timing + energy + structure
3. Fuse signals into show intent
4. Generate fixture commands
5. Enforce safety constraints
6. Transmit DMX (Art-Net or FTDI)

The current active hardware profile is one OEM 7-channel laser via a Pknight Art-Net/sACN-to-DMX converter.

### 1.2 Runtime architecture
Main graph wiring is in:
- `src/photonic_synesthesia/graph/builder.py`

Execution order:
1. `audio_sense`
2. Parallel branches:
- audio analysis branch: `feature_extract -> beat_track -> structure_detect -> fusion`
- MIDI branch: `midi_sense -> fusion`
- CV branch: `cv_sense -> fusion`
3. `director_intent -> scene_select`
4. Parallel fixture branches:
- `laser_control`
- `moving_head_control`
- `panel_control`
5. merge at `interpreter`
6. `safety_interlock`
7. `dmx_output`

This is important: safety runs *before* DMX write, so unsafe commands are clamped before they can hit universe output.

### 1.3 State model (the contract between nodes)
State schema and defaults:
- `src/photonic_synesthesia/core/state.py`

The `PhotonicState` TypedDict carries:
- timing/frame counters
- raw audio buffer + extracted features
- beat info (bpm/phase/bar/confidence)
- structure classification and drop probability
- MIDI intent state (faders, filters, EQ, pad triggers)
- CV state (BPM read + waveform lookahead)
- fused BPM and source attribution
- dual-stream outputs (`rule_stream`, `ml_stream`)
- director intent
- scene state
- fixture commands
- DMX universe buffer
- safety state and per-node timings

If you need to reason about coupling risk or extension points, start here.

### 1.4 Configuration model and startup behavior
Typed config is in:
- `src/photonic_synesthesia/core/config.py`

Operational config files are:
- `config/default.yaml`
- `config/pknight_single_laser.yaml`

Startup validation is enforced in:
- `src/photonic_synesthesia/ui/cli.py` (`_validate_startup_config`)

Startup checks currently include:
- fixture profile exists
- fixture channel span does not exceed 512
- non-idle default scene file exists
- non-mock live mode has at least one enabled fixture

### 1.5 Sensor nodes
Audio input:
- `src/photonic_synesthesia/graph/nodes/audio_sense.py`
- Callback-driven `sounddevice` capture into deque ring buffer.

Feature extraction:
- `src/photonic_synesthesia/graph/nodes/feature_extract.py`
- Uses `librosa` for RMS, centroid, rolloff, onset-strength proxy for flux, mel-band energies, MFCCs.

Beat tracking:
- `src/photonic_synesthesia/graph/nodes/beat_track.py`
- Prefers BeatNet if available, falls back to madmom, else heuristic fallback.
- Maintains beat history and BPM smoothing via median intervals.

MIDI sensing:
- `src/photonic_synesthesia/graph/nodes/midi_sense.py`
- Captures XDJ-style CC/note data into faders, filters, EQ arrays, pad triggers.
- Infers coarse effects (`high_pass_sweep`, `low_pass_sweep`, etc.).

Computer vision:
- `src/photonic_synesthesia/graph/nodes/cv_sense.py`
- Optional screen-capture BPM OCR + waveform color lookahead.
- Rate-limited sampling with cached values.

### 1.6 Analysis and decision layers
Structure detection:
- `src/photonic_synesthesia/graph/nodes/structure_detect.py`
- Heuristic classifier for intro/verse/buildup/drop/breakdown/outro using RMS, slope, bass changes, and gap logic.

Fusion layer:
- `src/photonic_synesthesia/graph/nodes/fusion.py`
- Blends audio/CV BPM with confidence weighting + smoothing.
- Applies MIDI filter attenuation to low/mid/high bands.
- Produces `rule_stream` and lightweight `ml_stream` proxy outputs.

Director layer:
- `src/photonic_synesthesia/director/engine.py`
- Phrase-boundary gating to avoid chaotic scene switches.
- Produces intent: target scene, energy, style, color theme, strobe budget.

Scene selection:
- `src/photonic_synesthesia/graph/nodes/scene_select.py`
- Priority chain:
1. pad override
2. director target/drop logic
3. structure mapping
4. energy threshold adjustment
- Handles transition timing.

### 1.7 Fixture command generation
Fixture nodes:
- `src/photonic_synesthesia/graph/nodes/fixture_control.py`

LaserControl is currently aligned to OEM 7CH map:
- CH1 mode
- CH2 pattern
- CH3 X
- CH4 Y
- CH5 scan speed
- CH6 pattern speed
- CH7 zoom

Moving head and panel nodes are still present in architecture but currently not part of the single-laser hardware profile.

### 1.8 Safety stack
Two safety layers exist:

Interpreter layer:
- `src/photonic_synesthesia/graph/nodes/interpreter.py`
- `src/photonic_synesthesia/interpreters/safety.py`
- Applies per-frame smoothing, laser clamps, and strobe budget caps.

Interlock layer:
- `src/photonic_synesthesia/graph/nodes/safety_interlock.py`
- Heartbeat timeout detection
- Emergency stop blackout
- Laser y-axis + min-speed enforcement
- Strobe rate/duration/cooldown guard
- Graceful degradation when beat confidence is low
- Optional watchdog thread can blackout independently

This defense-in-depth design is one of the strongest parts of the codebase.

### 1.9 DMX transport and universe model
Universe utilities:
- `src/photonic_synesthesia/dmx/universe.py`
- Canonical model: 513 bytes (start code + 512 channels).

Output transport:
- `src/photonic_synesthesia/graph/nodes/dmx_output.py`
- Supports:
- FTDI serial DMX frame generation
- Art-Net UDP (`ArtNetTransmitter`)
- Rejects NaN/Inf channel writes.

Art-Net packet builder:
- `src/photonic_synesthesia/dmx/artnet.py`

For current hardware, path is Art-Net to Pknight, then Pknight to DMX fixture.

### 1.10 Test coverage signal
Useful tests:
- `tests/unit/test_safety_interlock.py`
- `tests/unit/test_production_hardening.py`
- `tests/unit/test_interpreter_node.py`
- `tests/unit/test_fusion_node.py`
- `tests/unit/test_midi_sense.py`
- `tests/unit/test_startup_validation.py`
- `tests/unit/test_dmx_universe_contract.py`

What is well covered:
- safety clamping and watchdog behavior
- DMX universe contracts
- finite-value rejection
- startup validation
- strobe budget effects

What is weaker:
- end-to-end latency/real-time determinism under load
- algorithm quality validation against labeled music datasets
- CV OCR robustness and failure modes
- fixture-profile runtime contract enforcement (profile-vs-code map drift)

---

## 2) Super Detailed Prompt for Deep-Research

Use this as-is (or with minor edits) in your deep research tool:

```text
You are performing a rigorous technical audit and improvement roadmap for a real-time Python lighting-control system.

Project summary:
- Name: Photonic Synesthesia
- Goal: music-reactive DMX control for DJ sets using sensor fusion
- Runtime model: LangGraph-like state machine with typed shared state
- Current hardware in scope: ONLY one OEM 4-lens RGBY laser using a 7-channel DMX profile, controlled via Pknight 4-Port Bi-Directional Art-Net/sACN -> DMX512 (3-pin)
- Transport in use now: Art-Net -> Pknight -> DMX -> laser
- Safety criticality: high (laser output)

Hard constraints:
1) Do not assume moving heads, LED panels, or other fixtures are available.
2) Recommendations must preserve a safe single-laser operational baseline.
3) Prioritize practical implementation changes over theoretical ones.
4) For each recommendation, include expected impact, implementation complexity, risk, and migration strategy.

Your mission:
Produce a deeply technical report on what should be improved, with evidence-backed recommendations.

Required output sections:
1. Executive summary (top 10 findings by impact/risk)
2. Architecture assessment
3. Real-time systems assessment (latency, jitter, thread model, backpressure, scheduling)
4. Signal-processing quality assessment
5. Safety engineering assessment (laser/strobe/heartbeat/failsafe)
6. DMX/Art-Net transport correctness assessment
7. Fixture profile and command-mapping consistency audit
8. Test strategy gap analysis
9. Security and robustness assessment (config poisoning, malformed values, network assumptions)
10. Prioritized roadmap (30/60/90 day)

Research scope and quality bar:
- Use primary sources wherever possible:
  - official docs/specs (Art-Net spec, DMX512 references, library docs)
  - peer-reviewed papers for beat tracking / MIR where applicable
  - maintainers’ official docs/issues for dependencies
- Explicitly distinguish facts vs your inference.
- Cite all claims with links.
- Flag uncertain claims.

Technical questions you must answer:
A) Graph/runtime design
- Is the current node ordering and synchronization model valid for deterministic real-time control?
- Are there race conditions, stale-state hazards, or command accumulation issues?
- Should fixture commands be regenerated idempotently per frame with stricter lifecycle semantics?

B) Audio + beat + structure
- Are current heuristics for structure detection robust across house/techno/trance/open-format DJ sets?
- Compare current beat-tracking fallback strategy against stronger alternatives.
- Recommend calibration/tuning strategy with objective metrics.

C) MIDI intent modeling
- Is the current XDJ-like CC map abstraction robust enough?
- Better way to infer DJ intent (effects, transitions, drops) from raw MIDI telemetry?

D) CV sensing
- Is OCR/template matching design robust for variable screen scale/theme/lighting?
- Should CV be optional advisory only vs hard contributor for BPM?
- What confidence framework should gate CV contribution?

E) Safety
- Evaluate layered safety design: interpreter + interlock + watchdog.
- Identify missing safeguards for laser operation (especially stationary beam risk, mode-channel lock, emergency stop propagation, startup interlocks).
- Recommend additional software safeguards and operational controls.

F) Transport/network
- Validate Art-Net packet handling and universe addressing assumptions.
- Broadcast vs unicast tradeoffs in unmanaged-switch DJ networks.
- Packet timing, refresh-rate, and blackout semantics best practices.

G) Config/profile contract
- Audit drift risk between fixture YAML profiles and hardcoded channel maps.
- Propose schema and runtime checks to guarantee profile-code consistency.
- Recommend migration toward profile-driven fixture control.

H) Testing and validation
- Design a robust test strategy with:
  - deterministic unit tests
  - integration tests with synthetic signal fixtures
  - hardware-in-the-loop smoke tests
  - performance tests (latency/jitter)
  - failure injection tests (sensor dropout, network loss, invalid values)

I) Production readiness
- What must be true before this can be trusted in a live show with only one laser?
- Provide a “minimum safe production checklist”.

Scoring rubric (for each recommendation):
- Impact: 1-5
- Safety impact: 1-5
- Complexity: 1-5
- Confidence: 1-5
- Time-to-implement estimate
- Blocking dependencies

Expected deliverable style:
- Be concrete and prescriptive.
- Prefer checklists, decision matrices, and phased migration plans.
- Include pseudo-code or patch sketches for critical recommendations.
- Include a final “Top 15 code changes” list mapped to file paths and test additions.
```

---

## 3) The 10 Most Important Files to Give Deep-Research

1. `src/photonic_synesthesia/graph/builder.py`
2. `src/photonic_synesthesia/core/state.py`
3. `src/photonic_synesthesia/core/config.py`
4. `src/photonic_synesthesia/graph/nodes/fixture_control.py`
5. `src/photonic_synesthesia/graph/nodes/safety_interlock.py`
6. `src/photonic_synesthesia/interpreters/safety.py`
7. `src/photonic_synesthesia/graph/nodes/dmx_output.py`
8. `src/photonic_synesthesia/dmx/artnet.py`
9. `src/photonic_synesthesia/graph/nodes/fusion.py`
10. `src/photonic_synesthesia/graph/nodes/structure_detect.py`

If you want to send 3 more optional context files:
- `src/photonic_synesthesia/graph/nodes/midi_sense.py`
- `src/photonic_synesthesia/ui/cli.py`
- `config/pknight_single_laser.yaml`

---

## 4) What Deep-Research Should Watch For First

1. Profile-code mismatch risk in laser channel semantics.
2. Real-time behavior under high CPU load (frame overruns, stale data).
3. Safety behavior under degraded confidence and dropped sensors.
4. Art-Net network behavior in mixed DJ unmanaged-switch environments.
5. Lack of objective, dataset-backed validation for structure/scene decisions.

