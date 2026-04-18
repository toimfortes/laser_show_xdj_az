# Runtime Context and CLI Extraction Design

## Summary

This design splits the current refactor target into two coordinated subprojects:

1. Decompose `src/photonic_synesthesia/platform/runtime_context.py`
2. Extract domain logic out of `src/photonic_synesthesia/ui/cli.py`

The order matters. `runtime_context.py` should land first because it is smaller and because it owns the shared playback/control-plane seam that `ui/cli.py`, `ui/web_panel.py`, and graph nodes already consume.

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

## Verified Source Constraints

The design is based on a repo scan, not just plan text.

- `runtime_context.py` currently exports a real public surface used by:
  - `ui/web_panel.py`
  - `ui/cli.py`
  - `graph/nodes/fixture_control.py`
  - `graph/nodes/ilda_output.py`
  - multiple unit tests
  - `platform/__init__.py`
- The currently consumed `runtime_context` symbols are:
  - `PlaybackContext`
  - `get_shared_control_plane_service`
  - `set_shared_control_plane_service`
  - `clear_shared_control_plane_service`
  - `get_shared_playback_context`
  - `set_shared_playback_context`
  - `clear_shared_playback_context`
- The current CLI seam is concentrated around:
  - public commands: `catalog_build`, `catalog_export_model_payloads`, `run`, `run_file`, `dmx_test`, `list_audio`, `list_midi`, `analyze`
  - large helper clusters for catalog building, semantic profiling, cue recipes, anti-template validation, pattern selection, and laser program generation

Those constraints make import compatibility and exit-code stability first-class requirements, not optional cleanup.

## Subproject A: `runtime_context.py` Decomposition

### Target module split

- `src/photonic_synesthesia/platform/runtime_context.py`
  - keep `PlaybackContext`
  - keep shared singleton accessor functions
  - keep compatibility re-exports for extracted helper APIs only if tests or internal callers need them during migration
  - keep thin orchestration methods that delegate to extracted helpers
- `src/photonic_synesthesia/platform/runtime_context_normalization.py`
  - move string/float normalization helpers here
- `src/photonic_synesthesia/platform/runtime_context_sections.py`
  - move section-scope resolution and section mutation helpers here
- `src/photonic_synesthesia/platform/runtime_context_operator_intents.py`
  - move operator-intent application policy here

### Public API and compatibility contract

Phase A is not allowed to break current import sites.

- Stable public API that must continue to work after Subproject A:
  - `PlaybackContext`
  - `get_shared_control_plane_service`
  - `set_shared_control_plane_service`
  - `clear_shared_control_plane_service`
  - `get_shared_playback_context`
  - `set_shared_playback_context`
  - `clear_shared_playback_context`
- Compatibility strategy:
  - keep the public imports above in `runtime_context.py`
  - keep `platform/__init__.py` re-exporting the same symbols
  - extracted helper modules are internal in Subproject A and are not imported directly outside `platform/` tests unless explicitly planned
  - test imports should continue to pass without bulk caller rewrites during the first extraction

### Named dependency that makes Subproject A first

Subproject B depends on one specific stabilized seam from Subproject A:

- `PlaybackContext` operator-intent mutation behavior and the shared playback/control-plane accessors must keep a stable contract before `cli.py` extraction touches `run` and `run_file`.
- The blocking call path is:
  - `ui/cli.py` creates and installs `PlaybackContext`
  - `ui/web_panel.py`, `fixture_control.py`, and `ilda_output.py` read from the shared playback context

That shared-state seam is the concrete reason Subproject A lands first. This is sequencing for state-contract stability, not because all CLI extraction work is inherently blocked.

### Boundary rules

- Pure transformation helpers should not depend on shared globals
- Section mutation helpers should operate on explicit section dictionaries/lists
- `PlaybackContext` remains the public coordinator for now, so external callers do not have to change heavily in the first phase
- Shared singleton accessors remain in `runtime_context.py` to avoid unnecessary churn across the web panel and CLI
- Shared singleton ownership remains in `runtime_context.py` under the existing module lock
- Extracted helper modules must not read or mutate `_SHARED_PLAYBACK_CONTEXT`, `_SHARED_CONTROL_PLANE_SERVICE`, or `_LOCK` directly
- Extracted helper modules must not import `ui/` modules

### Thread-safety contract

- `runtime_context.py` remains the sole owner of:
  - `_SHARED_PLAYBACK_CONTEXT`
  - `_SHARED_CONTROL_PLANE_SERVICE`
  - `_LOCK`
- All singleton reads/writes continue to happen through the existing accessor functions in `runtime_context.py`
- Extracted helper modules are pure or operate only on explicit objects already held by `PlaybackContext` methods while those methods hold their lock
- No new helper module may introduce its own process-global state

### Success criteria

- `runtime_context.py` is reduced from 865 LOC to 450 LOC or less
- no new `platform/runtime_context_*` module is smaller than 80 LOC unless it contains exactly one cohesive responsibility with at least one dedicated test file
- all existing imports of the stable public API continue to pass unchanged
- extracted helpers are covered by focused unit tests
- playback/operator intent behavior remains unchanged as proven by:
  - existing runtime/playback tests
  - at least one new focused test file for normalization/section mutation behavior
  - no snapshot diff in `PlaybackContext.snapshot()` structure for equivalent inputs

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

This split is structural extraction, not dependency inversion by itself. The architectural claim is narrowed accordingly: `cli.py` becomes a thin shell over a domain package with a defined facade.

### `showplan` public facade

Subproject B must define one stable facade for `ui/cli.py` to call.

- `src/photonic_synesthesia/showplan/__init__.py` must expose only the entrypoints the CLI needs
- Initial planned public entrypoints:
  - `build_show_catalog_entry(...)`
  - `build_semantic_profile(...)`
  - `resolve_show_sections(...)`
  - `build_cue_recipe(...)`
  - `build_laser_program(...)`
  - `anti_template_validation(...)`
  - `select_section_patterns(...)`
  - `build_model_payload(...)`
- Helper modules under `showplan/` remain internal unless promoted through `showplan/__init__.py`

### Boundary rules

- Click decorators and command functions stay in `ui/cli.py`
- extracted modules must not import Click
- extracted modules should accept explicit inputs and return plain Python data structures
- command functions in `cli.py` should orchestrate domain calls, not contain scoring/planning logic inline
- CLI-layer code includes:
  - Click decorators and option parsing
  - config loading and startup validation
  - command-to-domain wiring
  - output formatting and process exit behavior
- Domain-layer code includes:
  - catalog building
  - semantic profiling
  - section/cue/laser planning
  - anti-template scoring and model payload assembly
- Borderline rule:
  - persistence adapters may live outside `ui/cli.py`, but CLI remains responsible for deciding when to print, exit, or raise `click.ClickException`
- `showplan/` modules must not import `ui/cli.py`
- `showplan/` sibling modules may only depend on lower-level helpers or the package facade patterns defined in the implementation plan

### Circular-import guardrails

- `showplan/__init__.py` may import from leaf modules, but leaf modules must not import from `showplan.__init__`
- no `showplan/*` module may import another sibling for convenience if the dependency can be inverted into a smaller shared helper
- `runtime_context_*` helpers must not import one another cyclically through `runtime_context.py`
- each new module introduced in either subproject must be added to a simple import-smoke test that imports the public facade and the main host files

### Exception and exit-code contract

- `showplan/` functions may raise ordinary Python exceptions internally, but `ui/cli.py` remains the translation boundary
- user-facing command failures must continue to surface as current CLI failures or `click.ClickException`, not raw tracebacks, unless the current command already intentionally crashes
- extraction must not change successful command exit code `0` behavior
- extraction must not change known failure exit-code semantics without an explicit planned test update

### Success criteria

- `ui/cli.py` is reduced from 5321 LOC to 1500 LOC or less
- at least 70% of the LOC removed from `ui/cli.py` lands in `showplan/` modules covered by direct unit tests
- `ui/cli.py` contains no cue-recipe, anti-template, pattern-selection, or laser-program algorithm bodies beyond thin facade calls
- extracted logic is testable without invoking Click commands
- existing CLI behavior and outputs remain stable as proven by:
  - named command-level smoke coverage for `catalog_build`, `catalog_export_model_payloads`, `run_file`, and `analyze`
  - golden comparisons for named show-plan/model-payload outputs
  - unchanged importability of the CLI entrypoint

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
- add an import-smoke test for the stable `runtime_context` public API and `platform.__init__` re-exports
- add a snapshot or structural-equivalence assertion for `PlaybackContext.snapshot()` on a canonical fixture

### Subproject B

- keep existing CLI-facing tests passing
- add module-level tests for extracted show-planning helpers
- verify named command flows still work through the CLI entrypoints
- add golden-output comparisons for at least:
  - one `catalog_build` entry payload
  - one resolved show-section payload
  - one exported model payload

### Golden and smoke anchors

“Representative” is too vague. The implementation plans must name concrete anchors.

- CLI smoke anchors:
  - `catalog_build`
  - `catalog_export_model_payloads`
  - `run_file`
  - `analyze`
- Golden anchors:
  - one canonical small-room show plan
  - one canonical model payload export
  - one canonical playback metadata binding result

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

### Slice-to-module mapping

- Slice 1: `catalog.py`, `semantic_profile.py`
- Slice 2: `cue_recipe.py`
- Slice 3: `validation.py`, `selection.py`
- Slice 4: `laser_program.py`, `model_payloads.py`
- Slice 5: final `ui/cli.py` shell cleanup and facade tightening

### Rollback policy

- Rollback unit for Subproject A:
  - one extracted helper module plus its host-file delegation changes
- Rollback unit for Subproject B:
  - one slice from the mapping above
- Stop conditions for any slice:
  - import smoke test fails
  - named command smoke test regresses
  - golden artifact diff is unexplained
  - exit-code behavior changes unexpectedly
- Recovery rule:
  - revert the current slice only
  - keep prior slices intact if their verification remains green

## Risks and Controls

- Risk: extraction changes behavior subtly because helpers currently rely on module-local coupling
  - Control: keep public orchestration shape stable in phase 1 and add regression tests before moving code
- Risk: `cli.py` extraction turns into broad domain redesign
  - Control: preserve current algorithms first, improve boundaries second
- Risk: too many modules created without clear ownership
  - Control: each extracted file must have one responsibility and one reason to change

## Module Ownership Inventory Requirements

The implementation plans must inventory these before moving code:

- module-level constants and maps in `ui/cli.py`
- normalization helpers and operator-intent helpers in `runtime_context.py`
- shared singleton state in `runtime_context.py`
- any file-level caches, registries, or generated preview/model payload helpers that currently rely on module scope

No extraction task should move functions without also assigning ownership for the constants and state they depend on.

## Decision

Proceed with two implementation plans:

1. `runtime_context.py` decomposition plan
2. `cli.py` domain extraction plan

Execution order:

1. Implement `runtime_context.py` decomposition
2. Implement `cli.py` extraction on top of those cleaner boundaries
