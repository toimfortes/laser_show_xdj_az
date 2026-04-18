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
- live playback scope targeting logic
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

## Measurement and Verification Conventions

All numeric targets in this design use one explicit counting and comparison method.

- LOC counter: `cloc`
- Counted metric: `code`
- Language filter: Python only
- Exclusions: blank lines and comments are excluded by `cloc` default behavior
- Baseline and target command for host files:
  - `cloc --quiet --json --include-lang=Python src/photonic_synesthesia/platform/runtime_context.py src/photonic_synesthesia/ui/cli.py`
- "LOC removed from `ui/cli.py`" means `baseline code - post-change code` from `cloc`
- "70% of removed LOC lands in `showplan/`" means:
  - `cloc --quiet --json --include-lang=Python src/photonic_synesthesia/showplan`
  - compare new `showplan/` code added during the extraction against code removed from `ui/cli.py`
- Measurement rule:
  - all reported LOC numbers in plans, commits, and verification notes must come from these exact `cloc` commands
  - `wc -l`, editor counters, and GitHub diff counts are not acceptable substitutes for success-criteria accounting

The implementation plans must use these exact commands for baseline and completion checks.

## Subproject A: `runtime_context.py` Decomposition

### Target module split

- `src/photonic_synesthesia/platform/runtime_context.py`
  - keep `PlaybackContext`
  - keep shared singleton accessor functions
  - keep thin orchestration methods that delegate to extracted helpers
- `src/photonic_synesthesia/platform/runtime_context_normalization.py`
  - move string/float normalization helpers here
- `src/photonic_synesthesia/platform/runtime_context_playback_scope.py`
  - move live playback scope resolution and section-target selection helpers here
- `src/photonic_synesthesia/platform/runtime_context_section_mutations.py`
  - move section mutation helpers here
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
  - extracted helper modules are internal in Subproject A
  - no extracted helper function is part of the stable public API
  - existing tests that only use the stable API should continue to pass unchanged
  - if a test needs a moved private helper, that test must be updated to import from the helper's owning internal module as part of the same slice

### Named dependency that makes Subproject A first

Subproject B depends on one specific stabilized seam from Subproject A:

- `PlaybackContext` operator-intent mutation behavior and the shared playback/control-plane accessors must keep a stable contract before `cli.py` extraction touches `run` and `run_file`.
- The blocking call path is:
  - `ui/cli.py` creates and installs `PlaybackContext`
  - `ui/web_panel.py`, `fixture_control.py`, and `ilda_output.py` read from the shared playback context

That shared-state seam is the concrete reason Subproject A lands first. This is sequencing for state-contract stability, not because all CLI extraction work is inherently blocked.

### Boundary rules

- Pure transformation helpers should not depend on shared globals
- Section mutation helpers should operate on explicit copied section dictionaries/lists
- `PlaybackContext` remains the public coordinator for now, so external callers do not have to change heavily in the first phase
- Shared singleton accessors remain in `runtime_context.py` to avoid unnecessary churn across the web panel and CLI
- Shared singleton ownership remains in `runtime_context.py` under the existing module lock
- Extracted helper modules must not read or mutate `_SHARED_PLAYBACK_CONTEXT`, `_SHARED_CONTROL_PLANE_SERVICE`, or `_LOCK` directly
- Extracted helper modules must not import `ui/` modules
- Extracted helper modules are internal only. They are not re-exported from `runtime_context.py` or `platform/__init__.py`.

### Thread-safety contract

- `runtime_context.py` remains the sole owner of:
  - `_SHARED_PLAYBACK_CONTEXT`
  - `_SHARED_CONTROL_PLANE_SERVICE`
  - `_LOCK`
- All singleton reads/writes continue to happen through the existing accessor functions in `runtime_context.py`
- Extracted helper modules must be safe to call without the caller holding `_LOCK`
- `PlaybackContext` methods may hold `_LOCK` only while copying mutable state out and while writing final results back
- Extracted helper modules must operate on immutable inputs or deep-copied mutable inputs and return new values to apply
- No helper may rely on "caller already holds the lock" as an implicit precondition
- No new helper module may introduce its own process-global state
- Standalone safety rule:
  - if a helper can only be called correctly while the caller holds `_LOCK`, that helper does not qualify for extraction
  - extracted helpers must be reusable with ordinary unit tests and pure inputs, without reproducing `PlaybackContext` lock discipline

### Success criteria

- `runtime_context.py` is reduced from 865 LOC to 450 LOC or less
- no new `platform/runtime_context_*` module is smaller than 40 `cloc` code lines unless it exports exactly one public class or one public function and has at least one dedicated test file
- all existing imports of the stable public API continue to pass unchanged
- extracted helpers are covered by focused unit tests
- playback/operator intent behavior remains unchanged as proven by:
  - existing runtime/playback tests
  - at least one new focused test file for normalization/section mutation behavior
  - deep-dict equality for `PlaybackContext.snapshot()` on a canonical fixture after masking non-deterministic fields:
    - `session_id`
    - `server_time`
    - `metadata_bound_at`
    - `transport_revision` only when the test intentionally updates transport state
  - import-smoke assertions for:
    - `photonic_synesthesia.platform.runtime_context`
    - `photonic_synesthesia.platform`
    - exact assertion logic:
      - import succeeds
      - the seven stable public symbols are present
      - import does not instantiate `ControlPlaneStateService`
      - import does not create a `PlaybackContext`
      - import does not require Click context or hardware/network setup

## Subproject B: `cli.py` Domain Extraction

### Target module split

- `src/photonic_synesthesia/ui/cli.py`
  - keep Click groups/commands
  - keep command argument parsing
  - keep startup validation and top-level orchestration
- `src/photonic_synesthesia/showplan/catalog.py`
  - catalog entry construction
  - precomputed show-plan loading/saving adapters
- `src/photonic_synesthesia/showplan/sections.py`
  - show-section generation and persisted-section resolution
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
- `src/photonic_synesthesia/showplan/types.py`
  - shared domain types, protocols, and reusable type aliases that sibling modules may import safely

This split is structural extraction, not dependency inversion by itself. The architectural claim is narrowed accordingly: `cli.py` becomes a thin shell over a domain package with a defined facade.

### `showplan` public facade

Subproject B must define one stable facade for `ui/cli.py` to call. The facade is the only domain import surface the CLI may use.

- `src/photonic_synesthesia/showplan/__init__.py` must expose only the entrypoints the CLI needs
- `src/photonic_synesthesia/showplan/types.py` must expose the shared data contracts the facade uses
- `ui/cli.py` may import only:
  - facade entrypoints from `photonic_synesthesia.showplan`
  - shared contract aliases or typed dictionaries from `photonic_synesthesia.showplan.types`
- `ui/cli.py` must not import leaf `showplan/*` modules directly
- Initial planned public entrypoints:
  - `build_show_catalog_entry(*, audio_file: Path, duration_seconds: float, structure_markers: list[dict[str, Any]], track_key: str, track_title: str, track_artist: str, selection_mode: str, selection_variance: float, venue_mode: str, rekordbox_source: Path | None, rekordbox_track_id: str = "", rekordbox_average_bpm: float | None = None, web_enrichment: dict[str, Any] | None = None) -> dict[str, Any]`
  - `build_semantic_profile(*, track_title: str, track_artist: str, duration_seconds: float, structure_markers: list[dict[str, Any]], rekordbox_average_bpm: float | None = None, web_enrichment: dict[str, Any] | None = None) -> dict[str, Any]`
  - `resolve_show_sections(persisted_show_plan: dict[str, Any] | None, markers: list[dict[str, Any]], duration_seconds: float, *, track_seed: str, semantic_profile: dict[str, Any] | None = None, selection_mode: str | None = None, selection_variance: float | None = None, venue_mode: str | None = None, metadata_confidence: dict[str, Any] | None = None) -> list[dict[str, Any]]`
  - `build_cue_recipe(*, kind: str, context: str, laser_pattern: str, mover_pattern: str, wash_pattern: str, led_pattern: str, laser_enabled: bool, movers_enabled: bool, washes_enabled: bool, leds_enabled: bool, section_role: str, venue_mode: str, venue_profile: dict[str, Any], transition_intent: dict[str, Any], cue_family_id: str, lead_family: str, fixture_role_map: dict[str, dict[str, Any]], capability_graph: dict[str, dict[str, Any]], capability_notes: list[str], metadata_confidence: dict[str, Any] | None) -> dict[str, Any]`
  - `build_laser_program(*, track_seed: str, base_pattern: str, kind: str, context: str, ordinal: int, profile: dict[str, Any], venue_mode: str) -> dict[str, Any]`
  - `anti_template_validation(*, track_key: str, show_sections: list[dict[str, Any]], semantic_profile: dict[str, Any] | None, recent_catalog_entries: list[dict[str, Any]] | None = None) -> dict[str, Any]`
  - `select_section_patterns(*, kind: str, context: str, profile: dict[str, Any], track_seed: str, marker_name: str, ordinal: int, previous_patterns: dict[str, str | None], pattern_history: dict[str, list[str]] | None, usage_count_by_family: dict[str, dict[str, int]] | None, semantic_profile: dict[str, Any] | None, selection_mode: str, energy_scale: float, selection_variance: float) -> dict[str, str]`
  - `build_catalog_model_payload(*, track_key: str, track_title: str, track_artist: str, duration_seconds: float, structure_markers: list[dict[str, Any]], show_sections: list[dict[str, Any]], selection_mode: str, selection_variance: float, venue_mode: str, rekordbox_track_id: str = "", rekordbox_average_bpm: float | None = None, semantic_profile: dict[str, Any] | None = None, metadata_confidence: dict[str, Any] | None = None, web_enrichment: dict[str, Any] | None = None, motif_registry: dict[str, Any] | None = None, show_fingerprint: dict[str, Any] | None = None, anti_template_validation: dict[str, Any] | None = None, scorer_bundle: dict[str, Any] | None = None, preview_artifacts: dict[str, Any] | None = None) -> dict[str, Any]`
- Owning modules:
  - `build_show_catalog_entry` -> `showplan/catalog.py`
  - `build_semantic_profile` -> `showplan/semantic_profile.py`
  - `resolve_show_sections` -> `showplan/sections.py`
  - `build_cue_recipe` -> `showplan/cue_recipe.py`
  - `build_laser_program` -> `showplan/laser_program.py`
  - `anti_template_validation` -> `showplan/validation.py`
  - `select_section_patterns` -> `showplan/selection.py`
  - `build_catalog_model_payload` -> `showplan/model_payloads.py`
- Helper modules under `showplan/` remain internal unless promoted through `showplan/__init__.py`
- Ownership rule:
  - `resolve_show_sections` is domain logic and belongs only to `showplan/sections.py`
  - `runtime_context_playback_scope.py` owns only live playback/operator scope targeting against already-existing section state
  - no Platform helper may generate or rebuild show-plan sections for catalog or CLI flows

### Subproject B import-migration contract

- `showplan/` is a new internal domain package with one public facade consumed by `ui/cli.py`
- There is no compatibility promise for importing private planning helpers from `ui/cli.py`
- Production cutover rule:
  - `ui/cli.py` switches to `showplan` facade imports slice by slice
  - tests that currently reach private helper functions in `ui/cli.py` must migrate in the same slice that moves that helper
- End-of-project rule:
  - `ui/cli.py` retains only command-shell helpers and no re-export aliases for extracted domain functions

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
- `showplan/` modules must not import from `platform/runtime_context*`; the CLI reads runtime context and passes explicit inputs into facade entrypoints
- `showplan/` sibling modules may only depend on lower-level helpers or `showplan/types.py`
- `showplan/sections.py` owns show-plan section resolution and persisted-plan fallback behavior
- `runtime_context_playback_scope.py` owns live playback section targeting for operator-intent scope only
- `showplan/` leaf modules must not import `showplan/__init__.py`
- if two `showplan/` siblings need a shared contract, that contract must move to `showplan/types.py` rather than creating a sibling-to-sibling cycle

### Circular-import guardrails

- `showplan/__init__.py` may import from leaf modules, but leaf modules must not import from `showplan.__init__`
- shared types and reusable typed contracts must live in `showplan/types.py`
- leaf `showplan/*` modules may import `showplan/types.py`, but must not import `showplan.__init__`
- no `showplan/*` module may import another sibling for convenience if the dependency can be inverted into `showplan/types.py` or a smaller leaf helper
- `runtime_context_*` helpers must not import one another cyclically through `runtime_context.py`
- each new module introduced in either subproject must be added to an import-smoke test that asserts:
  - import succeeds
  - expected public symbols exist
  - importing does not instantiate shared singleton state
  - importing does not require Click context or hardware/network access
- concrete import-smoke assertions required:
  - `import photonic_synesthesia.platform.runtime_context as rc`
    - assert `hasattr(rc, "PlaybackContext")`
    - assert `hasattr(rc, "get_shared_playback_context")`
    - assert `rc.get_shared_playback_context() is None` before any test setup creates one
  - `from photonic_synesthesia.platform import PlaybackContext`
    - assert symbol import succeeds without side effects
  - `import photonic_synesthesia.showplan as sp`
    - assert facade symbols listed in this spec exist
  - `import photonic_synesthesia.showplan.types as spt`
    - assert shared contract aliases or typed dictionaries exist
  - none of these imports may open sockets, require Click invocation, or access hardware transport layers

### Exception and exit-code contract

- `showplan/` functions may raise ordinary Python exceptions internally, but `ui/cli.py` remains the translation boundary
- user-facing command failures must continue to surface as current CLI failures or `click.ClickException`, not raw tracebacks, unless the current command already intentionally crashes
- extraction must not change successful command exit code `0` behavior
- baseline failure contract to preserve unless an implementation plan changes it explicitly:
  - `catalog_build` failure path -> exit code `1`
  - `catalog_export_model_payloads` failure path -> exit code `1`
  - `run` failure path -> exit code `1`
  - `run_file` failure path -> exit code `1`
  - `dmx_test` failure path -> exit code `1`
  - `list_audio` failure path -> exit code `1`
  - `list_midi` failure path -> exit code `1`
  - `analyze` failure path -> exit code `1`
- implementation plans must begin with an explicit baseline inventory command:
  - `rg -n "SystemExit\\(|sys\\.exit\\(|ClickException|UsageError|Abort|ctx\\.exit\\(" src/photonic_synesthesia/ui/cli.py src/photonic_synesthesia/ui/web_panel.py`
- implementation plans must define a domain error family such as `ShowplanError` and map it explicitly at the CLI seam according to the preserved command baseline:
  - `ShowplanError` -> `click.ClickException` or `SystemExit(1)`
  - extraction must not introduce new non-zero exit codes without updating the spec and command tests
  - command-level tests must assert exit code `1` for preserved failure paths and `0` for success

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
- add an import-smoke test for the stable `runtime_context` public API and `platform.__init__` re-exports using the concrete assertions defined above
- add a snapshot or structural-equivalence assertion for `PlaybackContext.snapshot()` on a canonical fixture

### Subproject B

- keep existing CLI-facing tests passing
- add module-level tests for extracted show-planning helpers
- verify named command flows still work through the CLI entrypoints
- add an import-smoke test for `photonic_synesthesia.showplan` and `photonic_synesthesia.showplan.types`
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
  - `tests/fixtures/showplan/canonical_small_room_show_plan.json`
  - `tests/fixtures/showplan/canonical_model_payload.json`
  - `tests/fixtures/runtime_context/canonical_playback_snapshot.json`
- Fixture-source anchors for generating or validating those goldens:
  - `config/pknight_single_laser.yaml`
  - `config/default.yaml`
  - `config/scenes/drop_intense.json`
- Required test-path binding:
  - the implementation plans must create or update tests that read exactly these fixture paths rather than describing them generically
  - each golden fixture must be serialized as normalized JSON with sorted keys
- Existing config anchors that the golden fixtures should be derived from or reference explicitly:
  - `config/fixtures/laser_aucd_cx338b_hybrid.yaml`
- Comparator rule:
  - use deep dictionary equality on normalized JSON payloads
  - serialize through one normalization helper before comparison
  - mask non-deterministic fields such as:
    - `provenance.generated_at`
    - `provenance.generator_host`
    - `session_id`
    - `server_time`
    - `metadata_bound_at`
    - `transport_revision` only in tests that intentionally mutate transport state

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

- Slice 1: `types.py`, `catalog.py`, `semantic_profile.py`, `sections.py`
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
  - rollback after one failed smoke run may be retried once after an obvious test-fix
  - rollback is mandatory after:
    - two failed smoke runs for the same slice
    - one unexplained golden diff
    - one import-smoke failure that indicates a cycle or side-effecting import

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
