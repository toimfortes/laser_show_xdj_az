# CLI Domain Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract show-planning and catalog-building domain logic out of `src/photonic_synesthesia/ui/cli.py` into a `showplan` package while preserving command behavior and exit-code semantics.

**Architecture:** Introduce `src/photonic_synesthesia/showplan/` as a pure-input domain package with a narrow facade in `showplan/__init__.py` and shared contracts in `showplan/types.py`. Migrate helper clusters slice by slice so `ui/cli.py` becomes a Click shell over facade calls instead of a host for planning algorithms.

**Tech Stack:** Python 3.13, Click, pytest, `cloc`, JSON fixtures, existing CLI and planner tests

---

## File Map

- Modify: `src/photonic_synesthesia/ui/cli.py`
- Create: `src/photonic_synesthesia/showplan/__init__.py`
- Create: `src/photonic_synesthesia/showplan/types.py`
- Create: `src/photonic_synesthesia/showplan/catalog.py`
- Create: `src/photonic_synesthesia/showplan/sections.py`
- Create: `src/photonic_synesthesia/showplan/semantic_profile.py`
- Create: `src/photonic_synesthesia/showplan/cue_recipe.py`
- Create: `src/photonic_synesthesia/showplan/validation.py`
- Create: `src/photonic_synesthesia/showplan/selection.py`
- Create: `src/photonic_synesthesia/showplan/laser_program.py`
- Create: `src/photonic_synesthesia/showplan/model_payloads.py`
- Create: `tests/unit/test_showplan_imports.py`
- Modify: `tests/unit/test_show_catalog.py`
- Modify: `tests/unit/test_show_planner.py`
- Modify: `tests/unit/test_production_hardening.py`

### Task 1: Seed the `showplan` Package

**Files:**
- Create: `src/photonic_synesthesia/showplan/__init__.py`
- Create: `src/photonic_synesthesia/showplan/types.py`
- Create: `tests/unit/test_showplan_imports.py`

- [ ] **Step 1: Write the failing import-smoke tests**

```python
import photonic_synesthesia.showplan as showplan
import photonic_synesthesia.showplan.types as showplan_types


def test_showplan_facade_import_smoke() -> None:
    for name in (
        "build_show_catalog_entry",
        "build_semantic_profile",
        "resolve_show_sections",
        "build_cue_recipe",
        "build_laser_program",
        "anti_template_validation",
        "select_section_patterns",
        "build_catalog_model_payload",
    ):
        assert hasattr(showplan, name)


def test_showplan_types_import_smoke() -> None:
    assert hasattr(showplan_types, "ShowSection")
```

- [ ] **Step 2: Run the new test to verify RED**

Run: `pytest tests/unit/test_showplan_imports.py -q`

Expected: FAIL because the package does not exist yet.

- [ ] **Step 3: Add the minimal package seed**

Create `showplan/types.py` with small typed aliases only:

```python
from typing import Any, TypeAlias

ShowSection: TypeAlias = dict[str, Any]
StructureMarker: TypeAlias = dict[str, Any]
SemanticProfile: TypeAlias = dict[str, Any]
ModelPayload: TypeAlias = dict[str, Any]
```

Create `showplan/__init__.py` with placeholder imports that will be filled as slices land.

- [ ] **Step 4: Run the import-smoke test to verify GREEN**

Run: `pytest tests/unit/test_showplan_imports.py -q`

Expected: PASS once the facade exports exist.

- [ ] **Step 5: Commit**

```bash
git add src/photonic_synesthesia/showplan/__init__.py src/photonic_synesthesia/showplan/types.py tests/unit/test_showplan_imports.py
git commit -m "test: seed showplan package import surface"
```

### Task 2: Extract Catalog, Semantic Profile, and Section Resolution

**Files:**
- Create: `src/photonic_synesthesia/showplan/catalog.py`
- Create: `src/photonic_synesthesia/showplan/semantic_profile.py`
- Create: `src/photonic_synesthesia/showplan/sections.py`
- Modify: `src/photonic_synesthesia/showplan/__init__.py`
- Modify: `src/photonic_synesthesia/ui/cli.py`
- Modify: `tests/unit/test_show_catalog.py`
- Modify: `tests/unit/test_show_planner.py`
- Modify: `tests/unit/test_production_hardening.py`

- [ ] **Step 1: Write failing direct-import tests for the extracted entrypoints**

```python
from photonic_synesthesia.showplan import (
    build_semantic_profile,
    build_show_catalog_entry,
    resolve_show_sections,
)


def test_showplan_sections_resolve_show_sections_matches_existing_shape() -> None:
    resolved = resolve_show_sections(
        {"show_sections": [{"id": "section_000", "label": "Auto Intro", "kind": "intro", "start_seconds": 0.0, "end_seconds": 0.25}]},
        [],
        64.0,
        track_seed="fixture",
    )
    assert isinstance(resolved, list)
    assert resolved
```

- [ ] **Step 2: Run the targeted tests to verify RED**

Run: `pytest tests/unit/test_showplan_imports.py tests/unit/test_show_catalog.py tests/unit/test_show_planner.py tests/unit/test_production_hardening.py -q`

Expected: FAIL on missing showplan entrypoints.

- [ ] **Step 3: Move the current implementations without behavior changes**

Move:
- `_build_show_catalog_entry` -> `showplan/catalog.py`
- `_build_semantic_profile` -> `showplan/semantic_profile.py`
- `_resolve_show_sections` and its local stale-check helpers -> `showplan/sections.py`

Update `showplan/__init__.py` to export those functions.

Keep temporary compatibility aliases in `ui/cli.py`:

```python
from photonic_synesthesia.showplan import (
    build_show_catalog_entry as _build_show_catalog_entry,
    build_semantic_profile as _build_semantic_profile,
    resolve_show_sections as _resolve_show_sections,
)
```

- [ ] **Step 4: Re-run the catalog and planner tests**

Run: `pytest tests/unit/test_showplan_imports.py tests/unit/test_show_catalog.py tests/unit/test_show_planner.py tests/unit/test_production_hardening.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/photonic_synesthesia/showplan/__init__.py src/photonic_synesthesia/showplan/catalog.py src/photonic_synesthesia/showplan/semantic_profile.py src/photonic_synesthesia/showplan/sections.py src/photonic_synesthesia/ui/cli.py tests/unit/test_showplan_imports.py tests/unit/test_show_catalog.py tests/unit/test_show_planner.py tests/unit/test_production_hardening.py
git commit -m "refactor: extract showplan catalog and sections helpers"
```

### Task 3: Extract Cue Recipe Logic

**Files:**
- Create: `src/photonic_synesthesia/showplan/cue_recipe.py`
- Modify: `src/photonic_synesthesia/showplan/__init__.py`
- Modify: `src/photonic_synesthesia/ui/cli.py`
- Modify: `tests/unit/test_show_planner.py`

- [ ] **Step 1: Write a failing direct-import test for `build_cue_recipe`**

```python
from photonic_synesthesia.showplan import build_cue_recipe


def test_build_cue_recipe_returns_expected_version() -> None:
    payload = build_cue_recipe(
        kind="drop",
        context="drop_launch",
        laser_pattern="fan",
        mover_pattern="sweep",
        wash_pattern="ambient",
        led_pattern="pulse",
        laser_enabled=True,
        movers_enabled=True,
        washes_enabled=True,
        leds_enabled=True,
        section_role="drop_1",
        venue_mode="small_room_50_100",
        venue_profile={"mode": "small_room_50_100"},
        transition_intent={"type": "bloom"},
        cue_family_id="small_room_50_100::drop_1::mover",
        lead_family="mover",
        fixture_role_map={"mover": {"role": "hero"}},
        capability_graph={"mover": {}},
        capability_notes=[],
        metadata_confidence=None,
    )
    assert payload["version"] == 6
```

- [ ] **Step 2: Run the planner tests to verify RED**

Run: `pytest tests/unit/test_show_planner.py -q`

Expected: FAIL on the missing `build_cue_recipe` export.

- [ ] **Step 3: Move `_cue_recipe` and its supporting private helpers into `showplan/cue_recipe.py`**

Do not drag Click or runtime-context imports into the new module. If helper constants are shared, move them into `showplan/types.py` or keep them local to `cue_recipe.py`.

- [ ] **Step 4: Rewire `ui/cli.py` to import the compatibility alias**

```python
from photonic_synesthesia.showplan import build_cue_recipe as _cue_recipe
```

- [ ] **Step 5: Run the relevant regression tests**

Run: `pytest tests/unit/test_show_planner.py tests/unit/test_show_catalog.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/photonic_synesthesia/showplan/__init__.py src/photonic_synesthesia/showplan/cue_recipe.py src/photonic_synesthesia/showplan/types.py src/photonic_synesthesia/ui/cli.py tests/unit/test_show_planner.py tests/unit/test_show_catalog.py
git commit -m "refactor: extract showplan cue recipe builder"
```

### Task 4: Extract Validation and Selection

**Files:**
- Create: `src/photonic_synesthesia/showplan/validation.py`
- Create: `src/photonic_synesthesia/showplan/selection.py`
- Modify: `src/photonic_synesthesia/showplan/__init__.py`
- Modify: `src/photonic_synesthesia/ui/cli.py`
- Modify: `tests/unit/test_show_planner.py`

- [ ] **Step 1: Write failing direct-import tests for `anti_template_validation` and `select_section_patterns`**

```python
from photonic_synesthesia.showplan import anti_template_validation, select_section_patterns


def test_anti_template_validation_returns_status() -> None:
    result = anti_template_validation(
        track_key="artist|track",
        show_sections=[],
        semantic_profile=None,
        recent_catalog_entries=[],
    )
    assert "status" in result


def test_select_section_patterns_returns_all_families() -> None:
    result = select_section_patterns(
        kind="drop",
        context="drop_launch",
        profile={},
        track_seed="fixture",
        marker_name="Drop A",
        ordinal=0,
        previous_patterns={"laser": None, "mover": None, "wash": None, "led": None},
        pattern_history=None,
        usage_count_by_family=None,
        semantic_profile=None,
        selection_mode="procedural",
        energy_scale=1.0,
        selection_variance=0.0,
    )
    assert set(result) == {"laser", "mover", "wash", "led"}
```

- [ ] **Step 2: Run the planner tests to verify RED**

Run: `pytest tests/unit/test_show_planner.py -q`

Expected: FAIL on missing facade exports.

- [ ] **Step 3: Move `_anti_template_validation`, `_select_section_patterns`, and their pure helper chains**

If either module needs a shared typed alias or contract, move that into `showplan/types.py` instead of creating sibling imports.

- [ ] **Step 4: Rewire the CLI compatibility aliases**

```python
from photonic_synesthesia.showplan import (
    anti_template_validation as _anti_template_validation,
    select_section_patterns as _select_section_patterns,
)
```

- [ ] **Step 5: Run regression coverage**

Run: `pytest tests/unit/test_show_planner.py tests/unit/test_show_catalog.py tests/unit/test_production_hardening.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/photonic_synesthesia/showplan/__init__.py src/photonic_synesthesia/showplan/validation.py src/photonic_synesthesia/showplan/selection.py src/photonic_synesthesia/showplan/types.py src/photonic_synesthesia/ui/cli.py tests/unit/test_show_planner.py tests/unit/test_show_catalog.py tests/unit/test_production_hardening.py
git commit -m "refactor: extract showplan validation and selection logic"
```

### Task 5: Extract Laser Program and Model Payload Builders

**Files:**
- Create: `src/photonic_synesthesia/showplan/laser_program.py`
- Create: `src/photonic_synesthesia/showplan/model_payloads.py`
- Modify: `src/photonic_synesthesia/showplan/__init__.py`
- Modify: `src/photonic_synesthesia/ui/cli.py`
- Modify: `tests/unit/test_show_planner.py`
- Modify: `tests/unit/test_show_catalog.py`

- [ ] **Step 1: Write failing direct-import tests**

```python
from photonic_synesthesia.showplan import build_catalog_model_payload, build_laser_program


def test_build_laser_program_returns_phrase_roles() -> None:
    payload = build_laser_program(
        track_seed="fixture",
        base_pattern="fan",
        kind="drop",
        context="drop_launch",
        ordinal=0,
        profile={},
        venue_mode="small_room_50_100",
    )
    assert payload["launch"]["label"] == "Launch Hook"


def test_build_catalog_model_payload_returns_sections() -> None:
    payload = build_catalog_model_payload(
        track_key="artist|track",
        track_title="Track",
        track_artist="Artist",
        duration_seconds=120.0,
        structure_markers=[],
        show_sections=[],
        selection_mode="procedural",
        selection_variance=0.0,
        venue_mode="small_room_50_100",
    )
    assert "sections" in payload
```

- [ ] **Step 2: Run the catalog/planner tests to verify RED**

Run: `pytest tests/unit/test_show_planner.py tests/unit/test_show_catalog.py -q`

Expected: FAIL on missing exports.

- [ ] **Step 3: Move `_laser_program` and `_build_catalog_model_payload`**

Keep the current data shape intact. If helper constants are shared, either keep them local or move them into `showplan/types.py`; do not import from `ui/cli.py`.

- [ ] **Step 4: Rewire the CLI compatibility aliases**

```python
from photonic_synesthesia.showplan import (
    build_catalog_model_payload as _build_catalog_model_payload,
    build_laser_program as _laser_program,
)
```

- [ ] **Step 5: Run regression coverage**

Run: `pytest tests/unit/test_show_planner.py tests/unit/test_show_catalog.py tests/unit/test_production_hardening.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/photonic_synesthesia/showplan/__init__.py src/photonic_synesthesia/showplan/laser_program.py src/photonic_synesthesia/showplan/model_payloads.py src/photonic_synesthesia/showplan/types.py src/photonic_synesthesia/ui/cli.py tests/unit/test_show_planner.py tests/unit/test_show_catalog.py tests/unit/test_production_hardening.py
git commit -m "refactor: extract showplan laser and model payload builders"
```

### Task 6: Thin the CLI Shell and Verify Behavior

**Files:**
- Modify: `src/photonic_synesthesia/ui/cli.py`
- Modify: `tests/unit/test_show_catalog.py`
- Modify: `tests/unit/test_production_hardening.py`
- Modify: `tests/unit/test_showplan_imports.py`

- [ ] **Step 1: Remove leftover algorithm bodies from `ui/cli.py`**

The CLI should retain:
- Click decorators and command functions
- startup/config wiring
- output formatting
- process exit/exception translation

It should no longer define the migrated planning functions inline.

- [ ] **Step 2: Add the explicit exit-code baseline test coverage**

Use `CliRunner` assertions for:
- success path exit code `0`
- representative failure path exit code `1`

Example:

```python
def test_catalog_build_failure_stays_exit_code_one(monkeypatch) -> None:
    monkeypatch.setattr(cli_module, "_discover_rekordbox_xml", lambda: None)
    monkeypatch.setattr(cli_module, "_audio_file_duration_seconds", lambda _: (_ for _ in ()).throw(RuntimeError("boom")))
    result = CliRunner().invoke(cli, ["catalog", "build", "."])
    assert result.exit_code == 1
```

- [ ] **Step 3: Run the command-smoke coverage**

Run:

```bash
pytest tests/unit/test_showplan_imports.py tests/unit/test_show_catalog.py tests/unit/test_show_planner.py tests/unit/test_production_hardening.py -q
cloc --quiet --json --include-lang=Python src/photonic_synesthesia/ui/cli.py src/photonic_synesthesia/showplan
```

Expected:
- tests pass
- `ui/cli.py` trends toward the target LOC
- new `showplan/` code accounts for the extracted planning logic

- [ ] **Step 4: Commit**

```bash
git add src/photonic_synesthesia/ui/cli.py tests/unit/test_showplan_imports.py tests/unit/test_show_catalog.py tests/unit/test_show_planner.py tests/unit/test_production_hardening.py
git commit -m "refactor: thin cli shell over showplan facade"
```
