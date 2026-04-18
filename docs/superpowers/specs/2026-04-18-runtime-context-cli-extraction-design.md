# Runtime Context and CLI Extraction Design

## Summary

This design splits the current refactor target into two coordinated subprojects:

1. Decompose `src/photonic_synesthesia/platform/runtime_context.py`
2. Extract domain logic out of `src/photonic_synesthesia/ui/cli.py`

The order matters. `runtime_context.py` should land first because it is smaller, already functionally cohesive, and provides cleaner state/editing boundaries that the later CLI extraction can depend on.

## Goals

- Reduce file size and mixed responsibilities in `runtime_context.py` and `cli.py`
- Preserve existing behavior while improving module boundaries
- Make domain logic importable and testable without Click or global runtime state
- Keep refactors incremental so each phase can ship with regression coverage

## Non-Goals

- Rewriting the control plane or playback model
- Replacing Click with a new CLI framework
- Re-architecting the show-planning domain itself during extraction
- Performing unrelated cleanup in other subsystems

## Current Problems

### `runtime_context.py`

The file mixes several concerns:

- normalization helpers for operator input
- section-selection and scope logic
- section mutation policy for operator intents
- `PlaybackContext` lifecycle/state handling
- shared singleton accessors for playback/control-plane services

That makes the file harder to test in isolation and increases the chance that simple behavior edits require reading the entire module.

### `cli.py`

The file currently contains both:

- real CLI responsibilities: Click wiring, option parsing, startup/config validation, command dispatch
- domain responsibilities: show-plan generation, semantic profiling, cue/recipe construction, anti-template scoring, model payload construction, venue policy, and pattern/laser planning

This inverts the dependency direction. The UI shell owns the business logic instead of calling into a domain layer.

## Subproject A: `runtime_context.py` Decomposition

### Target module split

- `src/photonic_synesthesia/platform/runtime_context.py`
  - keep only `PlaybackContext`
  - keep shared singleton accessor functions
  - keep thin orchestration methods that delegate to extracted helpers
- `src/photonic_synesthesia/platform/runtime_context_normalization.py`
  - move string/float normalization helpers here
- `src/photonic_synesthesia/platform/runtime_context_sections.py`
  - move section-scope resolution and section mutation helpers here
- `src/photonic_synesthesia/platform/runtime_context_operator_intents.py`
  - move operator-intent application policy here

### Boundary rules

- Pure transformation helpers should not depend on shared globals
- Section mutation helpers should operate on explicit section dictionaries/lists
- `PlaybackContext` remains the public coordinator for now, so external callers do not have to change heavily in the first phase
- Shared singleton accessors remain in `runtime_context.py` to avoid unnecessary churn across the web panel and CLI

### Success criteria

- `runtime_context.py` becomes materially smaller and easier to scan
- extracted helpers are covered by focused unit tests
- playback/operator intent behavior remains unchanged

## Subproject B: `cli.py` Domain Extraction

### Target module split

- `src/photonic_synesthesia/ui/cli.py`
  - keep Click groups/commands
  - keep command argument parsing
  - keep startup validation and top-level orchestration
- `src/photonic_synesthesia/showplan/catalog.py`
  - catalog entry construction
  - precomputed show-plan loading/saving adapters
- `src/photonic_synesthesia/showplan/semantic_profile.py`
  - semantic profile and metadata confidence logic
- `src/photonic_synesthesia/showplan/cue_recipe.py`
  - cue family, recipe line, phaser, transition, and role-map construction
- `src/photonic_synesthesia/showplan/validation.py`
  - anti-template scoring, motif/fingerprint helpers, scorer bundle
- `src/photonic_synesthesia/showplan/selection.py`
  - pattern candidate ranking/selection and stable choice helpers
- `src/photonic_synesthesia/showplan/laser_program.py`
  - laser look/program construction and zone policy helpers
- `src/photonic_synesthesia/showplan/model_payloads.py`
  - model payload and candidate export helpers

The exact file split can be adjusted during planning, but the design goal is fixed: domain logic moves out of `ui/cli.py` and into importable modules with explicit responsibilities.

### Boundary rules

- Click decorators and command functions stay in `ui/cli.py`
- extracted modules must not import Click
- extracted modules should accept explicit inputs and return plain Python data structures
- command functions in `cli.py` should orchestrate domain calls, not contain scoring/planning logic inline

### Success criteria

- `cli.py` becomes primarily a command shell
- extracted logic is testable without invoking Click commands
- existing CLI behavior and outputs remain stable

## Data Flow

### `runtime_context.py`

Operator request -> normalization helpers -> scope resolution -> section mutation policy -> `PlaybackContext` state update -> snapshot/read APIs

### `cli.py`

Click command -> argument parsing -> domain service/helper calls -> artifact persistence/output formatting -> process exit

## Testing Strategy

### Subproject A

- keep existing runtime control-plane and playback context tests passing
- add focused unit tests around extracted normalization and operator-intent helpers
- verify no behavior change in section targeting, intensity mutation, and intent expiry behavior

### Subproject B

- keep existing CLI-facing tests passing
- add module-level tests for extracted show-planning helpers
- verify representative command flows still work through the CLI entrypoints

## Incremental Delivery

### Phase 1

Ship `runtime_context.py` decomposition first with behavior-preserving tests.

### Phase 2

Extract `cli.py` logic in slices:

- catalog/metadata helpers
- semantic/cue-recipe helpers
- validation/selection helpers
- laser/model-payload helpers
- final CLI shell cleanup

Each slice should leave the CLI runnable and covered by targeted tests.

## Risks and Controls

- Risk: extraction changes behavior subtly because helpers currently rely on module-local coupling
  - Control: keep public orchestration shape stable in phase 1 and add regression tests before moving code
- Risk: `cli.py` extraction turns into broad domain redesign
  - Control: preserve current algorithms first, improve boundaries second
- Risk: too many modules created without clear ownership
  - Control: each extracted file must have one responsibility and one reason to change

## Decision

Proceed with two implementation plans:

1. `runtime_context.py` decomposition plan
2. `cli.py` domain extraction plan

Execution order:

1. Implement `runtime_context.py` decomposition
2. Implement `cli.py` extraction on top of those cleaner boundaries
