# LLM Light Show Engineer PRD

## Goal

Evolve the planner from deterministic pattern picking into a constrained show-programming system that behaves more like a lighting engineer:

- understands track structure and genre semantics
- plans section-level cue intent instead of only pattern labels
- validates repetition and structural arc before saving
- stays fixture-feasible and safety-aware at runtime

## Principles

1. Safety before aesthetics
2. Structural correctness before novelty
3. Recipe-level intent before raw fixture output
4. Offline heavy reasoning, lightweight live playback
5. Human override remains first-class

## Current State

The repo already has:

- Rekordbox-backed section markers
- generated section plans for laser, mover, wash, and LED families
- offline catalog JSON
- web enrichment and evaluator payload export

Current limitation:

- the planner mostly chooses named patterns
- semantic track understanding is shallow
- evaluation can critique plans, but the catalog schema does not yet carry recipe-level programming intent

## Target Architecture

### Pass 1: Stable Evaluator Inputs

Keep model-facing inputs compact, versioned, and deterministic.

Deliverables:

- `model_payload` schema validation
- selected patterns always included in constrained candidate lists
- catalog export for offline evaluators

### Pass 2: Semantic Music Layer

Add a durable semantic layer derived from local structure, BPM, and web enrichment.

Deliverables:

- top-level `semantic_profile`
- genre hints, descriptors, style bias
- structure summary including first-drop timing and arc shape
- explicit provenance and confidence

### Pass 3: Recipe Layer

Add section-level cue recipes without removing the existing runtime primitives.

Deliverables:

- per-section `cue_recipe`
- intent, stage, transition strategy, timing master
- recipe families for laser, mover, wash, and LED
- additive compiler path from recipe data to existing runtime behavior

### Pass 4: Critic + Validator

Run strong offline evaluation against constrained section plans and reject structurally weak outputs.

Deliverables:

- repetition validator
- arc validator
- candidate-safe evaluator prompts
- approve/reject/apply loop for suggested changes

### Pass 5: Pre-viz Critique

Critique what the show looks like, not just what labels say.

Deliverables:

- per-section stills or short clips
- long-exposure composites
- visual clutter / contrast / climax feedback

### Pass 6: Live Integration

Use precomputed plans live while keeping runtime deterministic and safety-checked.

Deliverables:

- catalog-first playback binding
- operator override controls
- transport integration through existing runtime layers

## Data Model Changes

### `semantic_profile`

Stored at the catalog top level and mirrored into `model_payload.planner`.

Fields:

- `version`
- `track_identity`
- `genre_hints`
- `descriptors`
- `style_bias`
- `structure_summary`
- `confidence`

### `cue_recipe`

Stored per section in `show_sections`.

Fields:

- `version`
- `intent`
- `stage`
- `transition_strategy`
- `timing_master`
- `families`

Each family describes:

- `enabled`
- `group`
- `feature_group`
- `preset`
- `effect`
- `timing_master`
- `pattern`
- `zone_policy` for lasers

## Near-Term Implementation Order

1. Add `semantic_profile` to catalog generation and model payloads
2. Add `cue_recipe` to generated show sections
3. Refresh persisted generated fields when recipe schema changes
4. Extend tests around catalog and planner output
5. Add validator and critic application flow

## Non-Goals

- direct LLM generation of DMX or ILDA frames
- replacing the current runtime output engine in one pass
- removing deterministic procedural fallback

## Acceptance Criteria

- catalog entries include versioned `semantic_profile`
- generated sections include versioned `cue_recipe`
- stale persisted sections auto-refresh generated recipe fields
- evaluator payloads include semantic information without bloating the input
- existing runtime behavior remains functional with additive metadata
