# Runtime Context Decomposition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `src/photonic_synesthesia/platform/runtime_context.py` into focused internal helper modules while preserving the current public API and runtime behavior.

**Architecture:** Keep `PlaybackContext` and the shared singleton accessors in `runtime_context.py`, but move pure normalization, live playback scope targeting, section mutation helpers, and operator-intent mutation logic into internal `runtime_context_*` modules. The host file remains the public boundary and lock owner; extracted helpers take explicit inputs and return values without touching shared globals.

**Tech Stack:** Python 3.13, pytest, Click-adjacent runtime code, `cloc`, existing unit tests under `tests/unit`

---

## File Map

- Modify: `src/photonic_synesthesia/platform/runtime_context.py`
- Create: `src/photonic_synesthesia/platform/runtime_context_normalization.py`
- Create: `src/photonic_synesthesia/platform/runtime_context_playback_scope.py`
- Create: `src/photonic_synesthesia/platform/runtime_context_section_mutations.py`
- Create: `src/photonic_synesthesia/platform/runtime_context_operator_intents.py`
- Modify: `src/photonic_synesthesia/platform/__init__.py`
- Create: `tests/unit/test_runtime_context_imports.py`
- Create: `tests/unit/test_runtime_context_helpers.py`
- Modify: `tests/unit/test_runtime_control_plane_integration.py`
- Modify: `tests/unit/test_fixture_control.py`
- Modify: `tests/unit/test_ilda_output.py`
- Modify: `tests/unit/test_web_panel.py`

### Task 1: Baseline Guard Rails

**Files:**
- Create: `tests/unit/test_runtime_context_imports.py`
- Modify: `tests/unit/test_runtime_control_plane_integration.py`

- [ ] **Step 1: Write the failing import-smoke tests**

```python
from photonic_synesthesia import platform
from photonic_synesthesia.platform import runtime_context as runtime_context_module


def test_runtime_context_public_api_import_smoke() -> None:
    expected = {
        "PlaybackContext",
        "get_shared_control_plane_service",
        "set_shared_control_plane_service",
        "clear_shared_control_plane_service",
        "get_shared_playback_context",
        "set_shared_playback_context",
        "clear_shared_playback_context",
    }

    for name in expected:
        assert hasattr(runtime_context_module, name)

    assert runtime_context_module.get_shared_playback_context() is None


def test_platform_reexports_runtime_context_public_api() -> None:
    assert platform.PlaybackContext is runtime_context_module.PlaybackContext
    assert platform.get_shared_playback_context is runtime_context_module.get_shared_playback_context
```

- [ ] **Step 2: Run the targeted tests to confirm the baseline is green before refactor**

Run: `pytest tests/unit/test_runtime_context_imports.py tests/unit/test_runtime_control_plane_integration.py -q`

Expected: PASS. If this fails before refactor, stop and fix the baseline first.

- [ ] **Step 3: Add the canonical snapshot normalization assertion**

```python
def _normalized_playback_snapshot(snapshot: dict[str, object]) -> dict[str, object]:
    normalized = dict(snapshot)
    for key in ("session_id", "server_time", "metadata_bound_at"):
        normalized[key] = "<masked>"
    normalized["transport_revision"] = "<masked>"
    return normalized
```

Add one assertion in `tests/unit/test_runtime_control_plane_integration.py` that compares two snapshots from equivalent inputs using `_normalized_playback_snapshot`.

- [ ] **Step 4: Re-run the smoke and snapshot tests**

Run: `pytest tests/unit/test_runtime_context_imports.py tests/unit/test_runtime_control_plane_integration.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_runtime_context_imports.py tests/unit/test_runtime_control_plane_integration.py
git commit -m "test: add runtime context import and snapshot guards"
```

### Task 2: Extract Normalization Helpers

**Files:**
- Create: `src/photonic_synesthesia/platform/runtime_context_normalization.py`
- Modify: `src/photonic_synesthesia/platform/runtime_context.py`
- Create: `tests/unit/test_runtime_context_helpers.py`

- [ ] **Step 1: Write the failing normalization tests**

```python
from photonic_synesthesia.platform.runtime_context_normalization import (
    clamp,
    normalize_metadata_source,
    normalize_operator_intent,
    normalize_operator_scope,
    normalize_operator_target,
    normalize_selection_mode,
    normalize_selection_variance,
    normalize_venue_mode,
)


def test_normalize_selection_mode_falls_back_to_procedural() -> None:
    assert normalize_selection_mode("unknown-mode") == "procedural"


def test_normalize_selection_variance_clamps_to_unit_interval() -> None:
    assert normalize_selection_variance(1.7) == 1.0
    assert normalize_selection_variance(-1) == 0.0


def test_normalize_venue_mode_accepts_medium_room() -> None:
    assert normalize_venue_mode("medium-room-150-400") == "medium_room_150_400"
```

- [ ] **Step 2: Run the helper tests to verify RED**

Run: `pytest tests/unit/test_runtime_context_helpers.py -q`

Expected: FAIL with `ModuleNotFoundError` or missing symbol errors.

- [ ] **Step 3: Add the new normalization module with minimal exports**

```python
PLAYBACK_SELECTION_MODES = {"procedural", "ai_assisted", "local_ollama_cpu"}
PLAYBACK_VENUE_MODES = {"small_room_50_100", "medium_room_150_400"}
PLAYBACK_OPERATOR_INTENTS = {
    "darken",
    "brighten",
    "reduce_laser_density",
    "less_strobe",
    "favor_overhead",
    "freeze_hero_family",
    "hold_current_palette",
    "delay_peak",
    "promote_washes",
}
PLAYBACK_OPERATOR_SCOPES = {"current_section", "next_phrase", "track", "set"}
PLAYBACK_OPERATOR_TARGETS = {"all", "lasers", "movers", "washes", "leds", "strobes"}


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
```

Move the existing normalization functions here, rename them without leading underscores, then import them back into `runtime_context.py` with private aliases:

```python
from photonic_synesthesia.platform.runtime_context_normalization import (
    clamp as _clamp,
    normalize_metadata_source as _normalize_metadata_source,
    normalize_operator_intent as _normalize_operator_intent,
    normalize_operator_scope as _normalize_operator_scope,
    normalize_operator_target as _normalize_operator_target,
    normalize_selection_mode as _normalize_selection_mode,
    normalize_selection_variance as _normalize_selection_variance,
    normalize_venue_mode as _normalize_venue_mode,
)
```

- [ ] **Step 4: Run the normalization and integration tests**

Run: `pytest tests/unit/test_runtime_context_helpers.py tests/unit/test_runtime_control_plane_integration.py tests/unit/test_runtime_context_imports.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/photonic_synesthesia/platform/runtime_context.py src/photonic_synesthesia/platform/runtime_context_normalization.py tests/unit/test_runtime_context_helpers.py tests/unit/test_runtime_context_imports.py tests/unit/test_runtime_control_plane_integration.py
git commit -m "refactor: extract runtime context normalization helpers"
```

### Task 3: Extract Scope and Section Mutation Helpers

**Files:**
- Create: `src/photonic_synesthesia/platform/runtime_context_playback_scope.py`
- Create: `src/photonic_synesthesia/platform/runtime_context_section_mutations.py`
- Modify: `src/photonic_synesthesia/platform/runtime_context.py`
- Modify: `tests/unit/test_runtime_context_helpers.py`

- [ ] **Step 1: Write failing tests for scope targeting and section mutation**

```python
from photonic_synesthesia.platform.runtime_context_playback_scope import section_ids_for_scope
from photonic_synesthesia.platform.runtime_context_section_mutations import (
    promote_family_to_hero,
    set_family_intensity,
)


def test_section_ids_for_scope_returns_current_section() -> None:
    show_sections = [
        {"id": "a", "start_seconds": 0.0, "end_seconds": 8.0},
        {"id": "b", "start_seconds": 8.0, "end_seconds": 16.0},
    ]
    assert section_ids_for_scope(show_sections, 2.0, "current_section") == {"a"}


def test_promote_family_to_hero_updates_fixture_roles_and_cue_recipe() -> None:
    section = {
        "lead_family": "mover",
        "fixture_role_map": {"mover": {"role": "hero"}, "wash": {"role": "support"}},
        "cue_family_id": "small_room_50_100::intro::mover",
        "cue_recipe": {
            "lead_family": "mover",
            "cue_family_id": "small_room_50_100::intro::mover",
            "fixture_role_map": {"mover": {"role": "hero"}, "wash": {"role": "support"}},
        },
    }

    promote_family_to_hero(section, "wash")

    assert section["lead_family"] == "wash"
    assert section["fixture_role_map"]["wash"]["role"] == "hero"
    assert section["cue_recipe"]["lead_family"] == "wash"
```

- [ ] **Step 2: Run the scope/mutation tests to verify RED**

Run: `pytest tests/unit/test_runtime_context_helpers.py -q`

Expected: FAIL because the new modules do not exist yet.

- [ ] **Step 3: Move the pure helpers into their new modules**

Move:
- `_section_ids_for_scope` -> `section_ids_for_scope`
- `_set_family_intensity` -> `set_family_intensity`
- `_sync_cue_family_family_id` -> `sync_cue_family_family_id`
- `_promote_family_to_hero` -> `promote_family_to_hero`
- `_update_operator_override` -> `update_operator_override`
- `_apply_nested_change` -> `apply_nested_change`

Keep `runtime_context.py` using private aliases imported from the new modules.

- [ ] **Step 4: Run the direct and indirect regression tests**

Run: `pytest tests/unit/test_runtime_context_helpers.py tests/unit/test_runtime_control_plane_integration.py tests/unit/test_web_panel.py tests/unit/test_fixture_control.py tests/unit/test_ilda_output.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/photonic_synesthesia/platform/runtime_context.py src/photonic_synesthesia/platform/runtime_context_playback_scope.py src/photonic_synesthesia/platform/runtime_context_section_mutations.py tests/unit/test_runtime_context_helpers.py tests/unit/test_runtime_control_plane_integration.py tests/unit/test_web_panel.py tests/unit/test_fixture_control.py tests/unit/test_ilda_output.py
git commit -m "refactor: extract runtime context scope and mutation helpers"
```

### Task 4: Extract Operator-Intent Logic

**Files:**
- Create: `src/photonic_synesthesia/platform/runtime_context_operator_intents.py`
- Modify: `src/photonic_synesthesia/platform/runtime_context.py`
- Modify: `tests/unit/test_runtime_context_helpers.py`

- [ ] **Step 1: Write failing tests for operator-intent expiry and application**

```python
from photonic_synesthesia.platform.runtime_context_operator_intents import (
    apply_operator_intent_to_section,
    intent_expired,
)


def test_intent_expired_at_threshold() -> None:
    assert intent_expired({"expires_at": "at:5"}, [], 5.1, 10.0) is True


def test_apply_operator_intent_to_section_reduces_strobe() -> None:
    updated = apply_operator_intent_to_section(
        {
            "strobe_level": 0.8,
            "strobe_profile": {"ceiling": 0.9, "floor": 0.2},
            "cue_recipe": {},
        },
        intent="less_strobe",
        target="strobes",
        amount=0.5,
        duration_seconds=60.0,
    )

    assert updated["strobe_level"] == 0.4
    assert updated["strobe_profile"]["ceiling"] == 0.45
```

- [ ] **Step 2: Run helper tests to verify RED**

Run: `pytest tests/unit/test_runtime_context_helpers.py -q`

Expected: FAIL on missing module or symbols.

- [ ] **Step 3: Extract `_intent_expired` and `_apply_operator_intent_to_section`**

The new module should import only:
- `copy`
- `typing.Any`
- private aliases from the normalization, scope, and section-mutation modules

Do not import `PlaybackContext`, shared singletons, or `runtime_context.py`.

- [ ] **Step 4: Rewire `PlaybackContext` to use the extracted helpers**

Replace direct calls to `_intent_expired`, `_section_ids_for_scope`, and `_apply_operator_intent_to_section` with imported private aliases. Keep `_refresh_operator_intents_locked()` in `PlaybackContext`.

- [ ] **Step 5: Run the full runtime-context regression suite**

Run: `pytest tests/unit/test_runtime_context_imports.py tests/unit/test_runtime_context_helpers.py tests/unit/test_runtime_control_plane_integration.py tests/unit/test_web_panel.py tests/unit/test_fixture_control.py tests/unit/test_ilda_output.py -q`

Expected: PASS.

- [ ] **Step 6: Check LOC target and commit**

Run: `cloc --quiet --json --include-lang=Python src/photonic_synesthesia/platform/runtime_context.py src/photonic_synesthesia/platform/runtime_context_*.py`

Expected: `runtime_context.py` trends materially downward and the new modules account for the extracted code.

```bash
git add src/photonic_synesthesia/platform/runtime_context.py src/photonic_synesthesia/platform/runtime_context_operator_intents.py tests/unit/test_runtime_context_imports.py tests/unit/test_runtime_context_helpers.py tests/unit/test_runtime_control_plane_integration.py tests/unit/test_web_panel.py tests/unit/test_fixture_control.py tests/unit/test_ilda_output.py
git commit -m "refactor: extract runtime context operator intent helpers"
```

### Task 5: Final Runtime Context Verification

**Files:**
- Modify: `src/photonic_synesthesia/platform/runtime_context.py`
- Modify: `src/photonic_synesthesia/platform/__init__.py`

- [ ] **Step 1: Confirm `platform/__init__.py` still re-exports only the stable API**

Expected public surface:

```python
__all__ = [
    "ControlAuthorityService",
    "ControlPlaneStateService",
    "PlaybackContext",
    "clear_shared_control_plane_service",
    "clear_shared_playback_context",
    "get_shared_control_plane_service",
    "get_shared_playback_context",
    "set_shared_control_plane_service",
    "set_shared_playback_context",
]
```

- [ ] **Step 2: Run the full verification set**

Run:

```bash
pytest tests/unit/test_runtime_context_imports.py tests/unit/test_runtime_context_helpers.py tests/unit/test_runtime_control_plane_integration.py tests/unit/test_web_panel.py tests/unit/test_fixture_control.py tests/unit/test_ilda_output.py -q
cloc --quiet --json --include-lang=Python src/photonic_synesthesia/platform/runtime_context.py
```

Expected:
- pytest passes
- `runtime_context.py` is at or below the target LOC, or close enough that any remaining excess is explained before starting Subproject B

- [ ] **Step 3: Commit**

```bash
git add src/photonic_synesthesia/platform/runtime_context.py src/photonic_synesthesia/platform/__init__.py
git commit -m "refactor: finalize runtime context decomposition"
```
