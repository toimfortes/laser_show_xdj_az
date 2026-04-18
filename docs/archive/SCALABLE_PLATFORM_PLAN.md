# Scalable Platform Plan

Date: 2026-04-15
Status: Planning
Scope: Redesign Photonic Synesthesia as a scalable lighting platform for sophisticated multi-fixture, multi-universe, multi-operator deployments while preserving the current safety baseline.

## 0. Executive Summary

This plan reframes the project from a single-runtime controller into a platform with explicit control-plane, semantics, scene-program, execution, and output layers.

Primary outcomes:
- define stable platform contracts before feature expansion
- make the website a first-class control plane
- replace ad hoc fixture math with compiled scene programs
- split fast execution from slow inference and control traffic
- support replay, preview, ML, and multi-universe output from shared core abstractions

This plan does not cut scope. It reorders the work so the broad scope remains executable.

## 1. Problem Statement

The current codebase has the right ingredients for a scalable system, but they are still coupled through one mutable runtime state and fixture-specific logic:
- shared mutable state in `src/photonic_synesthesia/core/state.py`
- single-loop runtime in `src/photonic_synesthesia/graph/builder.py`
- heuristic ML placeholder in `src/photonic_synesthesia/graph/nodes/fusion.py`
- hardcoded fixture execution logic in `src/photonic_synesthesia/graph/nodes/fixture_control.py`
- stub web entrypoint in `src/photonic_synesthesia/ui/web_panel.py`

That architecture will not scale cleanly to:
- multiple fixture classes and semantic roles
- multiple universes and transports
- multiple operators and remote clients
- learned cue recommendation and scene proposal
- deterministic replay and preview

## 2. Architectural Principles

1. Platform contracts before features.
2. Safety authority stays in the execution path.
3. Website acts through typed commands, never direct state mutation.
4. Scene logic compiles to executable programs before output packing.
5. Learned models target semantic and authoring layers before raw DMX.
6. Replay and preview are core infrastructure, not optional tooling.
7. Transport is a pluggable output concern, not part of show semantics.

## 3. Target Platform Layers

### 3.1 Control Plane

Responsibilities:
- website and remote operator workflows
- command validation and authority arbitration
- live telemetry fan-out
- patch configuration
- scene authoring and publication
- replay and diagnostics control

Core outputs:
- `OperatorCommand`
- `PlatformEvent`
- audit log entries

### 3.2 Show Semantics Plane

Responsibilities:
- beat, downbeat, phrase, and structure interpretation
- energy, mood, and intent estimation
- director decisions
- cue recommendation
- transition policy

Core outputs:
- `SemanticFrame`
- `DirectorIntent`
- `CueRecommendation`

### 3.3 Scene Program Plane

Responsibilities:
- typed scene model
- fixture-role abstractions
- modulation source binding
- transition definitions
- compile authored scenes into executable fixture programs

Core outputs:
- `SceneIR`
- `CompiledSceneProgram`
- `FixtureExecutionPlan`

### 3.4 Execution Plane

Responsibilities:
- fast reactive modulation
- slow semantic inference
- command arbitration
- safety enforcement
- deterministic snapshot generation

Core outputs:
- `ExecutionSnapshot`
- `CompiledFrame`
- `SafetyVerdict`

### 3.5 Output Plane

Responsibilities:
- patch application
- universe packing
- transport routing
- node health and telemetry

Core outputs:
- `UniverseFrame`
- `TransportEnvelope`
- `OutputHealthReport`

## 4. Platform Contracts

These contracts must be implemented before major expansion.

### 4.1 OperatorCommand

Purpose:
- represent all operator intent entering the system

Minimum commands:
- arm
- disarm
- blackout
- clear_blackout
- set_global_intensity
- set_global_speed
- set_auto_mode
- hold_scene
- release_scene_hold
- launch_scene
- set_fixture_group_override
- clear_fixture_group_override
- set_palette_override
- set_transport_state
- start_replay
- stop_replay

Required fields:
- `command_id`
- `issued_at_ms`
- `issuer_id`
- `session_id`
- `command_type`
- `target`
- `payload`

### 4.2 PlatformEvent

Purpose:
- provide durable, observable runtime events for UI, logs, and replay

Minimum event types:
- command_accepted
- command_rejected
- safety_trip
- safety_cleared
- scene_transition_started
- scene_transition_completed
- fixture_fault
- transport_fault
- replay_started
- replay_stopped

### 4.3 SceneIR

Purpose:
- typed intermediate representation between authored scenes and runtime execution

Minimum fields:
- `scene_id`
- `version`
- `fixture_role_blocks`
- `modulation_bindings`
- `transition_rules`
- `safety_annotations`
- `metadata`

### 4.4 FixtureCapability

Purpose:
- describe what a fixture can do semantically and safely

Minimum fields:
- `fixture_type`
- `channel_roles`
- `attributes`
- `value_ranges`
- `safety_constraints`
- `timing_constraints`
- `transport_requirements`

### 4.5 PatchModel

Purpose:
- map logical fixtures to physical output topology

Minimum fields:
- `fixture_id`
- `profile_id`
- `semantic_roles`
- `groups`
- `universe_id`
- `start_address`
- `transport_id`
- `enabled`

### 4.6 ExecutionSnapshot

Purpose:
- deterministic inspection and replay surface

Minimum fields:
- `snapshot_version`
- `monotonic_ms`
- `active_scene_ids`
- `effective_overrides`
- `semantic_frame`
- `director_intent`
- `compiled_frames`
- `safety_state`
- `output_health`

## 5. Runtime Planes

### 5.1 Fast Loop

Target cadence:
- 40-100 Hz

Responsibilities:
- streaming audio feature updates
- beat pulse and transient response
- execution of already-compiled scene programs
- per-frame safety shaping
- universe staging

Hard rule:
- sole writer for safety-critical output buffers

### 5.2 Slow Loop

Target cadence:
- 2-10 Hz

Responsibilities:
- structure segmentation
- mood and intent prediction
- CV lookahead
- optional stem enrichment
- director recommendations
- scene proposals

Hard rule:
- never writes raw universe buffers

### 5.3 Control Loop

Mode:
- async and event-driven

Responsibilities:
- website traffic
- command bus
- replay controls
- patch edits
- diagnostics

Hard rule:
- writes intent through commands and publications only

## 6. System Components To Add

New modules proposed:
- `src/photonic_synesthesia/platform/contracts.py`
- `src/photonic_synesthesia/platform/commands.py`
- `src/photonic_synesthesia/platform/events.py`
- `src/photonic_synesthesia/platform/clock.py`
- `src/photonic_synesthesia/platform/replay.py`
- `src/photonic_synesthesia/platform/authority.py`
- `src/photonic_synesthesia/scenes/ir.py`
- `src/photonic_synesthesia/scenes/compiler.py`
- `src/photonic_synesthesia/patch/models.py`
- `src/photonic_synesthesia/patch/router.py`
- `src/photonic_synesthesia/execution/fast_loop.py`
- `src/photonic_synesthesia/execution/slow_loop.py`
- `src/photonic_synesthesia/execution/arbitration.py`
- `src/photonic_synesthesia/output/router.py`
- `src/photonic_synesthesia/output/transports/`

## 7. Migration Strategy

### Phase 1: Contracts And Boundaries

Deliverables:
- platform contract types
- command bus
- event bus
- monotonic clock abstraction
- state-domain split design

Acceptance:
- no new feature work lands without mapped contract ownership
- all control inputs can be represented as `OperatorCommand`

### Phase 2: Control Plane V1

Deliverables:
- real `photonic-web` service
- live telemetry and command APIs
- operator authority model
- Run, Safety, Overrides, Patch, Universe Monitor screens

Acceptance:
- one active control session
- multiple passive observer sessions
- no direct mutation of internal runtime state from web handlers

### Phase 3: Scene IR And Patch Kernel

Deliverables:
- typed `SceneIR`
- fixture capabilities
- patch model
- scene compiler
- generic fixture execution adapters

Acceptance:
- scene execution path works from compiled programs
- hardcoded fixture math remains only as a legacy fallback

### Phase 4: Replay And Preview Infrastructure

Deliverables:
- event log format
- deterministic snapshot format
- replay runner
- preview renderer hooks

Acceptance:
- replay reproduces scene/director transitions for captured runs

### Phase 5: Multi-Plane Runtime

Deliverables:
- fast loop
- slow loop
- control loop
- arbitration rules

Acceptance:
- slow-loop stall does not stop fast-loop output
- safety path remains deterministic under stress

### Phase 6: Transport Scale-Out

Deliverables:
- universe router
- transport adapter abstraction
- Art-Net hardening
- sACN support

Acceptance:
- same compiled frame can target multiple universes and transports

### Phase 7: ML And Authoring Expansion

Deliverables:
- semantic tag models
- cue recommendation
- scene authoring tools
- constrained scene proposal

Acceptance:
- learned outputs feed scene/program layers, not direct DMX

## 8. Acceptance Metrics

Platform metrics:
- command acknowledgment latency
- active control lease failover time
- event-stream freshness
- replay determinism rate

Execution metrics:
- fast-loop p50, p95, p99 frame time
- slow-loop staleness window
- blackout latency
- safety intervention frequency

Output metrics:
- universe pack time
- transport error rate
- output-node liveness

Semantics metrics:
- beat/downbeat accuracy on replay corpus
- structure-transition stability
- scene-switch churn rate

## 9. Risks

Primary risks:
- overloading LangGraph with responsibilities better served by a dedicated execution kernel
- expanding UI before command and event contracts stabilize
- keeping fixture hardcoding too long and delaying scene compiler authority
- building ML before deterministic replay exists

Mitigations:
- treat contracts as release gates
- keep fast-loop output authority isolated
- make replay infrastructure mandatory before ML
- enforce typed scene and patch compilation before advanced authoring

## 10. Immediate Next Actions

1. Create the control-plane website plan.
2. Create the scene IR and patch plan.
3. Implement platform contract modules.
4. Replace the web stub with a skeleton FastAPI service.
5. Draft a state-domain split from the current `PhotonicState`.

## 11. References

- Oculizer repository: <https://github.com/LandryBulls/Oculizer>
- Skip-BART paper: <https://arxiv.org/abs/2506.01482>
- musicnn repository: <https://github.com/jordipons/musicnn>
- musicnn paper: <https://arxiv.org/abs/1909.06654>
- librosa streaming docs: <https://librosa.org/doc/latest/generated/librosa.stream.html>
- Essentia streaming architecture: <https://essentia.upf.edu/streaming_architecture.html>
- BeatNet repository: <https://github.com/mjhydri/BeatNet>
- BeatNet paper: <https://arxiv.org/abs/2108.03576>
- BEAST paper: <https://arxiv.org/abs/2312.17156>
- Demucs repository: <https://github.com/facebookresearch/demucs>
- Spleeter repository: <https://github.com/deezer/spleeter>
- FastAPI events docs: <https://fastapi.tiangolo.com/advanced/events/>
- FastAPI WebSockets docs: <https://fastapi.tiangolo.com/advanced/websockets/>
- Art-Net specification: <https://art-net.org.uk/art-net-specification/>
- OLA project: <https://www.openlighting.org/ola/>
