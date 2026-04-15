# Scene IR And Patch Plan

Date: 2026-04-15
Status: Planning
Scope: Define the typed scene intermediate representation, fixture capability model, and patch kernel required for scalable execution, authoring, preview, replay, and ML integration.

## 0. Executive Summary

The current runtime loads scene JSON but still executes fixtures primarily through hardcoded per-fixture formulas. That is not a scalable substrate.

This plan introduces:
- a typed `SceneIR`
- fixture capability descriptors
- patch model and grouping
- compilation from authored scenes to executable fixture plans
- a migration path away from hardcoded fixture math as the default execution path

## 1. Problem Statement

Current constraints:
- scene files are loaded dynamically in `src/photonic_synesthesia/graph/nodes/scene_select.py`
- fixture behavior is still mostly hardcoded in `src/photonic_synesthesia/graph/nodes/fixture_control.py`
- fixture profiles are validated at startup but not used as runtime execution authority
- safety offsets are partly duplicated between config and runtime logic

Scalable requirements:
- author once, execute across many fixture types
- patch fixtures independently of scene semantics
- preview scenes without hardware
- replay compiled execution deterministically
- allow ML to recommend or generate scene programs safely

## 2. Design Principles

1. Scenes describe intent and modulation, not raw slot payloads.
2. Patch maps logical fixtures to physical topology.
3. Fixture capabilities are runtime authority for what can be targeted.
4. Compilation is explicit and inspectable.
5. Safety annotations are attached to capabilities and programs.
6. Transport is downstream of compilation.

## 3. Core Models

### 3.1 FixtureCapability

Purpose:
- describe what a fixture can do and what constraints apply

Minimum fields:
- `profile_id`
- `fixture_class`
- `attributes`
- `channel_roles`
- `value_ranges`
- `default_values`
- `timing_constraints`
- `safety_constraints`
- `semantic_roles`

Example attributes:
- dimmer
- strobe
- rgb
- color_wheel
- pan
- tilt
- pattern_select
- pattern_speed
- zoom
- scan_speed

### 3.2 PatchFixture

Purpose:
- bind a logical fixture to execution and transport context

Minimum fields:
- `fixture_id`
- `profile_id`
- `display_name`
- `groups`
- `semantic_roles`
- `universe_id`
- `start_address`
- `transport_id`
- `enabled`

### 3.3 SceneIR

Purpose:
- represent authored scene semantics prior to fixture-specific lowering

Minimum fields:
- `scene_id`
- `version`
- `metadata`
- `roles`
- `role_programs`
- `modulation_sources`
- `transition_policy`
- `trigger_policy`
- `safety_overrides`

### 3.4 RoleProgram

Purpose:
- define behavior for a semantic role such as `lead_spot`, `wash`, `laser_pattern`, `audience_blinder`, `fx_mover`

Minimum fields:
- `role_id`
- `attribute_targets`
- `effect_chain`
- `bindings`
- `priority`

### 3.5 CompiledSceneProgram

Purpose:
- fixture-specific executable result of scene compilation

Minimum fields:
- `scene_id`
- `compiled_version`
- `fixture_programs`
- `required_capabilities`
- `compiler_warnings`

### 3.6 FixtureExecutionPlan

Purpose:
- per-fixture program ready for fast-loop execution

Minimum fields:
- `fixture_id`
- `attribute_generators`
- `protected_channels`
- `update_policy`
- `fallback_values`

## 4. Scene Authoring Model

Authoring inputs should allow:
- semantic fixture roles
- per-role effect blocks
- modulation bindings to sources like beat, transient, bass, energy, mood, structure, director intent
- transition rules
- cue priorities
- safety-aware limits

Authoring should not require:
- universe knowledge
- channel offsets
- transport-specific addressing

## 5. Patch Model

Patch is the runtime bridge between abstract scenes and physical fixtures.

Patch responsibilities:
- fixture inventory
- grouping
- semantic role membership
- addressing
- universe assignment
- transport binding
- enable/disable state

Patch should support:
- one scene targeting many fixtures by role
- fixture substitution without scene rewrites
- multi-universe layouts
- fixture groups spanning universes

## 6. Compiler Pipeline

### 6.1 Validation

Checks:
- scene schema validity
- required role references
- modulation source validity
- capability availability
- safety annotation consistency

### 6.2 Lowering

Transforms:
- role programs -> candidate fixture targets
- generic attribute intents -> fixture-specific attributes
- modulation sources -> executable generators

### 6.3 Safety Pass

Checks:
- protected channels
- scan-speed minima
- tilt and pan clamps
- strobe policy compatibility
- attribute range clipping

### 6.4 Output

Artifacts:
- compiled scene program
- compiler warnings
- explainability report for preview and debugging

## 7. Runtime Integration

### 7.1 Current State

Current execution path:
- scene selected
- fixture nodes generate values directly from heuristics

### 7.2 Target State

Target execution path:
1. scene selection yields `SceneIR` or scene identifier
2. compiler returns `CompiledSceneProgram`
3. fast loop executes per-fixture programs against live modulation inputs
4. output plane packs resulting channel values into universes

### 7.3 Migration Strategy

Step 1:
- keep current fixture nodes as compatibility adapters

Step 2:
- move hardcoded logic into default compiled templates

Step 3:
- make compiled program execution the primary path

Step 4:
- relegate hardcoded formulas to legacy fallback only

## 8. Files And Modules To Add

Proposed modules:
- `src/photonic_synesthesia/scenes/models.py`
- `src/photonic_synesthesia/scenes/ir.py`
- `src/photonic_synesthesia/scenes/compiler.py`
- `src/photonic_synesthesia/scenes/validators.py`
- `src/photonic_synesthesia/scenes/runtime.py`
- `src/photonic_synesthesia/patch/models.py`
- `src/photonic_synesthesia/patch/loader.py`
- `src/photonic_synesthesia/patch/validators.py`
- `src/photonic_synesthesia/fixtures/capabilities.py`
- `src/photonic_synesthesia/fixtures/adapters/`

## 9. Safety Integration

Safety authority should move closer to capabilities and compiled plans.

Required changes:
- unify safety constraints from fixture profiles and runtime config
- derive protected channels from capability metadata instead of hardcoded offsets
- attach safety annotations to compiled plans
- keep final safety interlock as defense-in-depth

This reduces duplication currently visible between:
- `src/photonic_synesthesia/core/config.py`
- `src/photonic_synesthesia/graph/nodes/safety_interlock.py`
- `src/photonic_synesthesia/graph/nodes/fixture_control.py`

## 10. Website Integration

The website should use this system for:
- scene browsing
- compile previews
- patch editing
- fixture capability inspection
- quick-load profiles
- preview renderer
- compiler diagnostics

No website authoring surface should bypass `SceneIR` and patch validation.

## 11. Replay And ML Integration

Replay should store:
- selected scene id
- compiled scene version
- patch version
- effective fixture execution plans

ML should target:
- semantic tags
- cue recommendations
- scene proposal
- role-program generation

ML should not emit raw DMX as an early-stage integration target.

## 12. Phased Plan

### Phase 1: Model Definitions

Deliverables:
- capability model
- patch model
- scene IR model
- compiled plan model

Acceptance:
- typed schemas exist and validate sample fixtures and scenes

### Phase 2: Profile And Patch Authority

Deliverables:
- profile loader that yields capabilities
- patch loader
- validators for overlap, capability mismatch, and safety constraints

Acceptance:
- startup validates full patch and capability consistency

### Phase 3: Scene Compiler

Deliverables:
- compiler pipeline
- warning system
- explainability report

Acceptance:
- existing `drop_intense` scene can compile into fixture plans

### Phase 4: Runtime Adapters

Deliverables:
- fast-loop execution of compiled plans
- adapters for laser, moving head, panel classes

Acceptance:
- compiled plan execution reproduces or improves current fallback behavior

### Phase 5: Authoring And Preview

Deliverables:
- website compile preview
- patch editor integration
- scene diagnostics

Acceptance:
- authored scene can be compiled, previewed, and published without touching runtime code

## 13. Acceptance Metrics

Compiler metrics:
- compile time
- warning count
- unsupported capability count

Runtime metrics:
- fixture plan execution cost
- fallback usage rate
- safety correction count after compilation

Authoring metrics:
- scene validation error clarity
- patch validation error clarity
- preview fidelity against live execution

## 14. Risks

Primary risks:
- overfitting the IR to current fixture set
- leaking transport concerns into scenes
- keeping hardcoded fixture logic too long
- insufficient safety metadata in profiles

Mitigations:
- keep roles and attributes generic
- isolate transport to output plane
- make compiler explainability visible
- expand profile schema before large authoring efforts

## 15. Immediate Next Actions

1. Draft `FixtureCapability` schema.
2. Draft `PatchModel` schema.
3. Draft `SceneIR` schema.
4. Create sample compiled representation for `drop_intense`.
5. Decide which current fixture node logic becomes default template library content.
