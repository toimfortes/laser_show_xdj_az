# Section Runtime Overrides Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make existing authored `scene_id`, `fixture_mode`, `laser_pattern`, `mover_pattern`, `wash_pattern`, and `led_pattern` fields affect live runtime behavior without renaming any contracts or bypassing operator/safety authority.

**Architecture:** Extend the shared active-section resolver to expose the authored override fields, then wire those fields into the scene selector and family-specific runtime emitters. Use explicit mapping tables for pattern interpretation, keep `fixture_mode` as a small cross-family behavior preset, and preserve existing snapshot/API field names plus current `active_scene_id` overlay semantics.

**Tech Stack:** Python 3, pytest, existing graph node pipeline, `PlaybackContext` snapshots, FastAPI web panel, DMX + ILDA runtime nodes.

---

## File Structure

### Modified files

- `src/photonic_synesthesia/graph/nodes/section_dynamics.py`
  - Extend `SectionDynamics` with the authored override fields and add reusable mapping helpers/tables.
- `src/photonic_synesthesia/graph/nodes/scene_select.py`
  - Insert active-section `scene_id` into the existing priority stack after operator controls and MIDI pad overrides.
- `src/photonic_synesthesia/graph/nodes/fixture_control.py`
  - Wire `laser_pattern`, `mover_pattern`, `wash_pattern`, `led_pattern`, and `fixture_mode` into DMX laser, moving-head, and panel runtime behavior.
- `src/photonic_synesthesia/graph/nodes/ilda_output.py`
  - Wire `laser_pattern` and `fixture_mode` into ILDA geometry/motion posture while preserving phrase-window timing.
- `tests/unit/test_runtime_nodes.py`
  - Add section override resolver coverage for authored scene/mode/pattern fields and mapping helpers.
- `tests/unit/test_scene_select.py`
  - Add scene-priority tests for active section `scene_id`, manual overrides, MIDI pad overrides, invalid scene ids, and short sections.
- `tests/unit/test_fixture_control.py`
  - Add DMX laser, mover, panel, and `fixture_mode` live-behavior tests.
- `tests/unit/test_ilda_output.py`
  - Add ILDA geometry override and `fixture_mode` posture tests.
- `tests/unit/test_web_panel.py`
  - Add regression that existing field names (`fixture_mode`, pattern fields) remain the live-edit contract.

### Existing files intentionally left behaviorally unchanged

- `src/photonic_synesthesia/platform/runtime_context.py`
  - No contract rename. Existing `update_show_section()` keys and `active_scene_id` overlay semantics stay intact.
- `tests/unit/test_runtime_context_helpers.py`
  - Existing overlay tests should continue to pass unchanged and be rerun in final verification.

## Task 1: Extend The Shared Active-Section Override Contract

**Files:**
- Modify: `src/photonic_synesthesia/graph/nodes/section_dynamics.py`
- Test: `tests/unit/test_runtime_nodes.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_resolve_active_section_dynamics_exposes_scene_mode_and_pattern_fields() -> None:
    state = create_initial_state()
    state["playback_snapshot"] = {
        "playhead_seconds": 4.0,
        "show_sections": [
            {
                "id": "sec-1",
                "start_seconds": 0.0,
                "end_seconds": 10.0,
                "scene_id": "drop_intense",
                "fixture_mode": "peak_return",
                "laser_pattern": "fan_burst",
                "mover_pattern": "pan_sweep",
                "wash_pattern": "bloom",
                "led_pattern": "chase",
            }
        ],
    }

    dynamics = resolve_active_section_dynamics(state)

    assert dynamics["scene_id"] == "drop_intense"
    assert dynamics["fixture_mode"] == "peak_return"
    assert dynamics["laser_pattern"] == "fan_burst"
    assert dynamics["mover_pattern"] == "pan_sweep"
    assert dynamics["wash_pattern"] == "bloom"
    assert dynamics["led_pattern"] == "chase"


def test_resolve_active_section_dynamics_coerces_non_string_overrides_to_defaults() -> None:
    state = create_initial_state()
    state["playback_snapshot"] = {
        "playhead_seconds": 4.0,
        "show_sections": [
            {
                "id": "sec-1",
                "start_seconds": 0.0,
                "end_seconds": 10.0,
                "scene_id": 123,
                "fixture_mode": None,
                "laser_pattern": ["fan"],
                "mover_pattern": {"mode": "hold"},
                "wash_pattern": False,
                "led_pattern": 7.5,
            }
        ],
    }

    dynamics = resolve_active_section_dynamics(state)

    assert dynamics["scene_id"] == "123"
    assert dynamics["fixture_mode"] == ""
    assert dynamics["laser_pattern"] == ""
    assert dynamics["mover_pattern"] == ""
    assert dynamics["wash_pattern"] == ""
    assert dynamics["led_pattern"] == ""


def test_pattern_mapping_helpers_resolve_authored_names_consistently() -> None:
    dmx_pattern, geometry_family = resolve_laser_pattern_override("fan_burst")
    mover_family = resolve_mover_pattern_family("hold")
    wash_render = resolve_panel_render_mode("bloom", "wash")
    led_render = resolve_panel_render_mode("chase", "led")

    assert dmx_pattern is not None
    assert geometry_family == "burst"
    assert mover_family == "hold"
    assert wash_render == "bloom"
    assert led_render == "chase"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_runtime_nodes.py -k "scene_mode_and_pattern_fields or non_string_overrides or pattern_mapping_helpers" -v`

Expected: FAIL with missing `SectionDynamics` keys and/or missing mapping helper names in `section_dynamics.py`.

- [ ] **Step 3: Write the minimal implementation**

```python
class SectionDynamics(TypedDict):
    section_id: str | None
    current_section: dict[str, Any] | None
    scene_id: str | None
    fixture_mode: str
    laser_pattern: str
    mover_pattern: str
    wash_pattern: str
    led_pattern: str
    intensity_multiplier: float
    motion_multiplier: float
    strobe_level: float
    laser_enabled: bool
    movers_enabled: bool
    washes_enabled: bool
    leds_enabled: bool
    panel_family: Literal["wash", "led"] | None


def _string_or_default(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return default


LASER_PATTERN_MAP = {
    "fan": {"dmx_pattern": 4, "geometry_family": "fan"},
    "fan_burst": {"dmx_pattern": 24, "geometry_family": "burst"},
    "liquid_sky": {"dmx_pattern": 0, "geometry_family": "sky"},
    "thin_scan": {"dmx_pattern": 12, "geometry_family": "scan"},
    "wave": {"dmx_pattern": 20, "geometry_family": "trace"},
}

MOVER_PATTERN_FAMILY_MAP = {
    "hold": "hold",
    "drift": "shape",
    "pan_sweep": "cross",
    "tilt_rise": "rise",
    "hit_sweep": "hits",
}

WASH_PATTERN_RENDER_MAP = {
    "ambient": "ambient",
    "fade": "fade",
    "bloom": "bloom",
    "punch": "punch",
    "breath": "breath",
}

LED_PATTERN_RENDER_MAP = {
    "pulse": "pulse",
    "chase": "chase",
    "sparkle": "sparkle",
    "ramp": "ramp",
    "fade": "fade",
}


def resolve_laser_pattern_override(pattern: str) -> tuple[int | None, str | None]:
    resolved = LASER_PATTERN_MAP.get(pattern)
    if resolved is None:
        return None, None
    return int(resolved["dmx_pattern"]), str(resolved["geometry_family"])


def resolve_mover_pattern_family(pattern: str) -> str | None:
    return MOVER_PATTERN_FAMILY_MAP.get(pattern)


def resolve_panel_render_mode(pattern: str, family: Literal["wash", "led"] | None) -> str | None:
    if family == "wash":
        return WASH_PATTERN_RENDER_MAP.get(pattern)
    if family == "led":
        return LED_PATTERN_RENDER_MAP.get(pattern)
    return LED_PATTERN_RENDER_MAP.get(pattern) or WASH_PATTERN_RENDER_MAP.get(pattern)


def resolve_active_section_dynamics(state: PhotonicState) -> SectionDynamics:
    current_section = _active_section(_snapshot_for_state(state))
    return SectionDynamics(
        section_id=_string_or_default(current_section.get("id") if isinstance(current_section, dict) else None) or None,
        current_section=current_section,
        scene_id=_string_or_default(current_section.get("scene_id") if isinstance(current_section, dict) else None) or None,
        fixture_mode=_string_or_default(current_section.get("fixture_mode") if isinstance(current_section, dict) else None),
        laser_pattern=_string_or_default(current_section.get("laser_pattern") if isinstance(current_section, dict) else None),
        mover_pattern=_string_or_default(current_section.get("mover_pattern") if isinstance(current_section, dict) else None),
        wash_pattern=_string_or_default(current_section.get("wash_pattern") if isinstance(current_section, dict) else None),
        led_pattern=_string_or_default(current_section.get("led_pattern") if isinstance(current_section, dict) else None),
        intensity_multiplier=_float_or_default(current_section.get("intensity_multiplier") if isinstance(current_section, dict) else None, 1.0),
        motion_multiplier=_float_or_default(current_section.get("motion_multiplier") if isinstance(current_section, dict) else None, 1.0),
        strobe_level=_float_or_default(current_section.get("strobe_level") if isinstance(current_section, dict) else None, 0.0),
        laser_enabled=_bool_or_default(current_section.get("laser_enabled") if isinstance(current_section, dict) else None, True),
        movers_enabled=_bool_or_default(current_section.get("movers_enabled") if isinstance(current_section, dict) else None, True),
        washes_enabled=_bool_or_default(current_section.get("washes_enabled") if isinstance(current_section, dict) else None, True),
        leds_enabled=_bool_or_default(current_section.get("leds_enabled") if isinstance(current_section, dict) else None, True),
        panel_family=_panel_family(current_section),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_runtime_nodes.py -k "scene_mode_and_pattern_fields or non_string_overrides or pattern_mapping_helpers" -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/photonic_synesthesia/graph/nodes/section_dynamics.py tests/unit/test_runtime_nodes.py
git commit -m "feat: expose authored section runtime override fields"
```

## Task 2: Wire `scene_id` Into `SceneSelectNode` Without Breaking Operator Priority

**Files:**
- Modify: `src/photonic_synesthesia/graph/nodes/scene_select.py`
- Test: `tests/unit/test_scene_select.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_scene_select_uses_active_section_scene_id_after_manual_and_pad_overrides(tmp_path: Path) -> None:
    _write_scene(tmp_path, "idle")
    _write_scene(tmp_path, "drop_intense")
    _write_scene(tmp_path, "intro_ambient")

    state = create_initial_state()
    state["scene_state"]["current_scene"] = "idle"
    state["playback_snapshot"] = {
        "playhead_seconds": 5.0,
        "show_sections": [
            {"id": "sec-1", "start_seconds": 0.0, "end_seconds": 10.0, "scene_id": "drop_intense"}
        ],
    }
    state["director_state"]["target_scene"] = "intro_ambient"
    state["director_state"]["allow_scene_transition"] = True

    node = SceneSelectNode(SceneConfig(scenes_dir=tmp_path))
    result = node(state)

    assert result["scene_state"]["pending_scene"] == "drop_intense"


def test_scene_select_pad_override_still_beats_section_scene_id(tmp_path: Path) -> None:
    _write_scene(tmp_path, "idle")
    _write_scene(tmp_path, "drop_intense")
    _write_scene(tmp_path, "intro_ambient")
    (tmp_path / "intro_ambient.json").write_text(
        json.dumps({"name": "intro_ambient", "pad_trigger": 1, "triggers": {"energy_threshold": 0.25}})
    )

    state = create_initial_state()
    state["scene_state"]["current_scene"] = "idle"
    state["midi_state"]["pad_triggers"] = [1]
    state["playback_snapshot"] = {
        "playhead_seconds": 5.0,
        "show_sections": [
            {"id": "sec-1", "start_seconds": 0.0, "end_seconds": 10.0, "scene_id": "drop_intense"}
        ],
    }

    node = SceneSelectNode(SceneConfig(scenes_dir=tmp_path))
    result = node(state)

    assert result["scene_state"]["pending_scene"] == "intro_ambient"


def test_scene_select_short_section_scene_id_only_updates_pending_scene(tmp_path: Path) -> None:
    _write_scene(tmp_path, "idle")
    _write_scene(tmp_path, "drop_intense")

    state = create_initial_state()
    state["timestamp"] = 10.0
    state["scene_state"]["current_scene"] = "idle"
    state["playback_snapshot"] = {
        "playhead_seconds": 0.1,
        "show_sections": [
            {"id": "sec-1", "start_seconds": 0.0, "end_seconds": 0.2, "scene_id": "drop_intense"}
        ],
    }

    node = SceneSelectNode(SceneConfig(scenes_dir=tmp_path, transition_time_s=1.0))
    result = node(state)

    assert result["scene_state"]["pending_scene"] == "drop_intense"
    assert result["scene_state"]["current_scene"] == "idle"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_scene_select.py -k "active_section_scene_id or pad_override_still_beats or short_section_scene_id" -v`

Expected: FAIL because `SceneSelectNode` does not yet read the active section `scene_id`.

- [ ] **Step 3: Write the minimal implementation**

```python
from photonic_synesthesia.graph.nodes.section_dynamics import resolve_active_section_dynamics


# Insert this block in SceneSelectNode.__call__ after the MIDI pad
# override section and before the director-target section.
if pending_scene is None:
    dynamics = resolve_active_section_dynamics(state)
    section_scene_id = dynamics.get("scene_id")
    if section_scene_id and self._is_valid_scene_name(section_scene_id):
        pending_scene = section_scene_id
    elif section_scene_id:
        logger.debug("Active section scene not found in catalog", scene_id=section_scene_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_scene_select.py -k "active_section_scene_id or pad_override_still_beats or short_section_scene_id" -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/photonic_synesthesia/graph/nodes/scene_select.py tests/unit/test_scene_select.py
git commit -m "feat: drive scene selection from authored section scene ids"
```

## Task 3: Add Canonical Pattern Mapping And Wire Laser + Mover Overrides

**Files:**
- Modify: `src/photonic_synesthesia/graph/nodes/section_dynamics.py`
- Modify: `src/photonic_synesthesia/graph/nodes/fixture_control.py`
- Modify: `src/photonic_synesthesia/graph/nodes/ilda_output.py`
- Test: `tests/unit/test_fixture_control.py`
- Test: `tests/unit/test_ilda_output.py`

- [ ] **Step 1: Write the failing tests**

```python
def _laser_state_with_section(
    *,
    section_overrides: dict[str, object],
    structure: MusicStructure = MusicStructure.DROP,
    beat_phase: float = 0.05,
    bpm: float = 128.0,
    energy: float = 0.72,
    timestamp: float = 1.37,
) -> PhotonicState:
    state = create_initial_state()
    state["timestamp"] = timestamp
    state["current_structure"] = structure
    state["beat_info"]["beat_phase"] = beat_phase
    state["fused_bpm"] = bpm
    state["audio_features"]["rms_energy"] = energy
    state["playback_snapshot"] = {
        "playhead_seconds": 1.0,
        "show_sections": [
            {
                "id": "section_000",
                "start_seconds": 0.0,
                "end_seconds": 8.0,
                **section_overrides,
            }
        ],
    }
    return state


def _ilda_node() -> ILDAOutputNode:
    fixture = FixtureConfig(
        id="laser-main",
        name="Main Laser",
        type="laser",
        profile="laser_aucd_cx338b_hybrid",
        start_address=1,
        enabled=True,
    )
    return ILDAOutputNode(
        ILDAConfig(enabled=True, points_per_frame=32),
        [fixture],
        LaserSafetyConfig(y_axis_max=96),
        fixtures_dir=Path("config/fixtures"),
    )


def _ilda_state_with_section(
    *,
    section_overrides: dict[str, object],
    structure: MusicStructure = MusicStructure.DROP,
) -> PhotonicState:
    state = create_initial_state()
    state["control_state"]["armed_live"] = True
    state["current_structure"] = structure
    state["playback_snapshot"] = {
        "playhead_seconds": 1.0,
        "show_sections": [
            {
                "id": "section_000",
                "start_seconds": 0.0,
                "end_seconds": 8.0,
                **section_overrides,
            }
        ],
    }
    return state


def test_laser_pattern_override_sets_dmx_pattern_channel() -> None:
    state = _laser_state_with_section(
        section_overrides={"laser_pattern": "fan_burst"},
        structure=MusicStructure.BREAKDOWN,
    )
    node = LaserControlNode([_laser_fixture()], LaserSafetyConfig(y_axis_max=96), fixtures_dir=Path("config/fixtures"))

    result = node(state)
    channel_values = result["fixture_commands"][0]["channel_values"]

    assert channel_values[1 + node.fixture_profiles["laser-main"].channel_map["pattern"]] != 0


def test_ilda_output_uses_section_laser_pattern_geometry_override() -> None:
    state = _ilda_state_with_section(
        section_overrides={"laser_pattern": "wave"},
        structure=MusicStructure.DROP,
    )
    node = _ilda_node()

    result = node(state)

    assert result["ilda_frames"][0]["geometry_family"] == "trace"


def test_mover_pattern_override_forces_motion_family_and_gobo() -> None:
    state = _moving_head_state_with_section(
        section_overrides={"mover_pattern": "hold"},
        structure=MusicStructure.DROP,
    )
    node = MovingHeadControlNode([_moving_head_fixture()], MovingHeadSafetyConfig())

    result = node(state)
    channel_values = result["fixture_commands"][0]["channel_values"]

    assert channel_values[1 + node.channel_map["gobo"]] == 64
    assert channel_values[1 + node.channel_map["strobe"]] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_fixture_control.py -k "laser_pattern_override_sets_dmx_pattern_channel or mover_pattern_override_forces_motion_family_and_gobo" -v`

Run: `pytest tests/unit/test_ilda_output.py -k "section_laser_pattern_geometry_override" -v`

Expected: FAIL because runtime nodes still ignore authored pattern fields.

- [ ] **Step 3: Write the minimal implementation**

```python
from photonic_synesthesia.graph.nodes.section_dynamics import (
    resolve_active_section_dynamics,
    resolve_laser_pattern_override,
    resolve_mover_pattern_family,
)


# In LaserControlNode.__call__:
commands = self._generate_laser_commands(
    fixture,
    scene,
    structure,
    beat_phase,
    bpm,
    energy,
    low_energy,
    state["timestamp"],
    motion_multiplier=dynamics["motion_multiplier"],
    laser_pattern=dynamics["laser_pattern"],
)

# In LaserControlNode._generate_laser_commands():
override_slot, _ = resolve_laser_pattern_override(laser_pattern)
if override_slot is not None:
    pattern = override_slot
elif structure == MusicStructure.DROP:
    pattern = int((current_time * 2) % 32)
elif structure == MusicStructure.BUILDUP:
    pattern = 10
elif structure == MusicStructure.BREAKDOWN:
    pattern = 0
else:
    pattern = int((current_time * 0.5) % 16)

# In MovingHeadControlNode.__call__:
commands = self._generate_moving_head_commands(
    fixture,
    scene,
    structure,
    beat_phase,
    bar_position,
    bpm,
    energy,
    state["timestamp"],
    phase_offset,
    program_look=program_look,
    palette=palette,
    color_drive=color_drive,
    intensity_multiplier=dynamics["intensity_multiplier"],
    motion_multiplier=dynamics["motion_multiplier"],
    strobe_level=dynamics["strobe_level"] if dynamics.get("current_section") is not None else 1.0,
    mover_pattern=dynamics["mover_pattern"],
)

# In MovingHeadControlNode._generate_moving_head_commands():
pattern_family = resolve_mover_pattern_family(mover_pattern)
mover_family = pattern_family or self._mover_family_for_program(structure, program_look)

# In ILDAOutputNode._frame_for_fixture():
_, geometry_override = resolve_laser_pattern_override(dynamics.get("laser_pattern", ""))
geometry_family = geometry_override or (
    str(program_look.get("geometry_family"))
    if program_look is not None and program_look.get("geometry_family")
    else self._geometry_family(structure, director["laser_aggression"])
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_fixture_control.py -k "laser_pattern_override_sets_dmx_pattern_channel or mover_pattern_override_forces_motion_family_and_gobo" -v`

Run: `pytest tests/unit/test_ilda_output.py -k "section_laser_pattern_geometry_override" -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/photonic_synesthesia/graph/nodes/section_dynamics.py src/photonic_synesthesia/graph/nodes/fixture_control.py src/photonic_synesthesia/graph/nodes/ilda_output.py tests/unit/test_fixture_control.py tests/unit/test_ilda_output.py
git commit -m "feat: wire authored pattern overrides into live emitters"
```

## Task 4: Wire Panel Pattern Routing And `fixture_mode` Live Semantics

**Files:**
- Modify: `src/photonic_synesthesia/graph/nodes/fixture_control.py`
- Modify: `src/photonic_synesthesia/graph/nodes/ilda_output.py`
- Test: `tests/unit/test_fixture_control.py`
- Test: `tests/unit/test_ilda_output.py`

- [ ] **Step 1: Write the failing tests**

```python
def _panel_state_with_section(
    *,
    section_overrides: dict[str, object],
    structure: MusicStructure = MusicStructure.DROP,
    beat_phase: float = 0.05,
    bar_position: int = 2,
    energy: float = 0.72,
    timestamp: float = 1.37,
) -> PhotonicState:
    state = create_initial_state()
    state["timestamp"] = timestamp
    state["current_structure"] = structure
    state["beat_info"]["beat_phase"] = beat_phase
    state["beat_info"]["bar_position"] = bar_position
    state["audio_features"]["rms_energy"] = energy
    state["playback_snapshot"] = {
        "playhead_seconds": 1.0,
        "show_sections": [
            {
                "id": "section_000",
                "start_seconds": 0.0,
                "end_seconds": 8.0,
                **section_overrides,
            }
        ],
    }
    return state


def _ilda_node() -> ILDAOutputNode:
    fixture = FixtureConfig(
        id="laser-main",
        name="Main Laser",
        type="laser",
        profile="laser_aucd_cx338b_hybrid",
        start_address=1,
        enabled=True,
    )
    return ILDAOutputNode(
        ILDAConfig(enabled=True, points_per_frame=32),
        [fixture],
        LaserSafetyConfig(y_axis_max=96),
        fixtures_dir=Path("config/fixtures"),
    )


def _ilda_state_with_section(
    *,
    section_overrides: dict[str, object],
    structure: MusicStructure = MusicStructure.DROP,
) -> PhotonicState:
    state = create_initial_state()
    state["control_state"]["armed_live"] = True
    state["current_structure"] = structure
    state["playback_snapshot"] = {
        "playhead_seconds": 1.0,
        "show_sections": [
            {
                "id": "section_000",
                "start_seconds": 0.0,
                "end_seconds": 8.0,
                **section_overrides,
            }
        ],
    }
    return state


def test_panel_prefers_led_pattern_when_panel_family_is_unknown() -> None:
    node = PanelControlNode([_panel_fixture()])
    state = _panel_state_with_section(
        section_overrides={
            "lead_family": "mover",
            "fixture_role_map": {},
            "wash_pattern": "bloom",
            "led_pattern": "chase",
        },
        structure=MusicStructure.VERSE,
    )

    result = node(state)
    channel_values = result["fixture_commands"][0]["channel_values"]

    assert channel_values[1 + node.channel_map["red"]] != channel_values[1 + node.channel_map["blue"]]


def test_panel_uses_wash_pattern_when_panel_family_is_wash() -> None:
    node = PanelControlNode([_panel_fixture()])
    state = _panel_state_with_section(
        section_overrides={
            "lead_family": "wash",
            "wash_pattern": "fade",
            "led_pattern": "chase",
        },
        structure=MusicStructure.BREAKDOWN,
    )

    result = node(state)
    channel_values = result["fixture_commands"][0]["channel_values"]

    assert channel_values[1 + node.channel_map["dimmer"]] < 180


def test_fixture_mode_peak_return_biases_panel_and_mover_output() -> None:
    panel_node = PanelControlNode([_panel_fixture()])
    mover_node = MovingHeadControlNode([_moving_head_fixture()], MovingHeadSafetyConfig())

    peak_panel = panel_node(_panel_state_with_section(section_overrides={"fixture_mode": "peak_return"}, structure=MusicStructure.DROP))
    intro_panel = panel_node(_panel_state_with_section(section_overrides={"fixture_mode": "intro"}, structure=MusicStructure.DROP))
    peak_mover = mover_node(_moving_head_state_with_section(section_overrides={"fixture_mode": "peak_return"}, structure=MusicStructure.DROP))
    intro_mover = mover_node(_moving_head_state_with_section(section_overrides={"fixture_mode": "intro"}, structure=MusicStructure.DROP))

    assert peak_panel["fixture_commands"][0]["channel_values"][1 + panel_node.channel_map["dimmer"]] > intro_panel["fixture_commands"][0]["channel_values"][1 + panel_node.channel_map["dimmer"]]
    assert peak_mover["fixture_commands"][0]["channel_values"][1 + mover_node.channel_map["pan_tilt_speed"]] > intro_mover["fixture_commands"][0]["channel_values"][1 + mover_node.channel_map["pan_tilt_speed"]]


def test_ilda_fixture_mode_intro_reduces_motion_posture() -> None:
    node = _ilda_node()
    peak = node(_ilda_state_with_section(section_overrides={"fixture_mode": "peak_return"}, structure=MusicStructure.DROP))
    intro = node(_ilda_state_with_section(section_overrides={"fixture_mode": "intro"}, structure=MusicStructure.DROP))

    peak_span = max(point["x"] for point in peak["ilda_frames"][0]["points"]) - min(point["x"] for point in peak["ilda_frames"][0]["points"])
    intro_span = max(point["x"] for point in intro["ilda_frames"][0]["points"]) - min(point["x"] for point in intro["ilda_frames"][0]["points"])

    assert peak_span > intro_span
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_fixture_control.py -k "panel_prefers_led_pattern_when_panel_family_is_unknown or panel_uses_wash_pattern_when_panel_family_is_wash or fixture_mode_peak_return_biases_panel_and_mover_output" -v`

Run: `pytest tests/unit/test_ilda_output.py -k "fixture_mode_intro_reduces_motion_posture" -v`

Expected: FAIL because `fixture_mode`, `wash_pattern`, and `led_pattern` do not yet affect live emitters.

- [ ] **Step 3: Write the minimal implementation**

```python
FIXTURE_MODE_BIAS = {
    "intro": {"motion": 0.75, "intensity": 0.9, "strobe": 0.5},
    "breakdown": {"motion": 0.65, "intensity": 0.85, "strobe": 0.35},
    "rebuild": {"motion": 1.15, "intensity": 1.0, "strobe": 0.8},
    "peak_return": {"motion": 1.25, "intensity": 1.1, "strobe": 1.0},
    "outro": {"motion": 0.6, "intensity": 0.75, "strobe": 0.25},
}


def _fixture_mode_bias(fixture_mode: str) -> dict[str, float]:
    return FIXTURE_MODE_BIAS.get(fixture_mode, {"motion": 1.0, "intensity": 1.0, "strobe": 1.0})


class MovingHeadControlNode:
    def __call__(self, state: PhotonicState) -> PhotonicState:
        mode_bias = _fixture_mode_bias(dynamics["fixture_mode"])
        commands = self._generate_moving_head_commands(
            fixture,
            scene,
            structure,
            beat_phase,
            bar_position,
            bpm,
            energy,
            state["timestamp"],
            phase_offset,
            program_look=program_look,
            palette=palette,
            color_drive=color_drive,
            intensity_multiplier=dynamics["intensity_multiplier"] * mode_bias["intensity"],
            motion_multiplier=dynamics["motion_multiplier"] * mode_bias["motion"],
            strobe_level=(dynamics["strobe_level"] if dynamics.get("current_section") is not None else 1.0) * mode_bias["strobe"],
            mover_pattern=dynamics["mover_pattern"],
        )


class PanelControlNode:
    def __call__(self, state: PhotonicState) -> PhotonicState:
        panel_family = dynamics.get("panel_family")
        panel_pattern = (
            dynamics["wash_pattern"] if panel_family == "wash"
            else dynamics["led_pattern"] if panel_family == "led"
            else dynamics["led_pattern"] or dynamics["wash_pattern"]
        )
        mode_bias = _fixture_mode_bias(dynamics["fixture_mode"])
        commands = self._generate_panel_commands(
            fixture,
            structure,
            beat_phase,
            bar_position,
            energy,
            time_since_drop,
            state["timestamp"],
            palette=palette,
            color_drive=color_drive,
            strobe_budget_hz=strobe_budget_hz,
            subphrase_role=subphrase_role,
            intensity_multiplier=dynamics["intensity_multiplier"] * mode_bias["intensity"],
            motion_multiplier=dynamics["motion_multiplier"] * mode_bias["motion"],
            strobe_level=(dynamics["strobe_level"] if dynamics.get("current_section") is not None else 1.0) * mode_bias["strobe"],
            panel_render_mode=resolve_panel_render_mode(panel_pattern, panel_family),
        )

# In PanelControlNode._generate_panel_commands():
if panel_render_mode == "chase":
    render_mode = "dual_cycle"
elif panel_render_mode == "sparkle":
    render_mode = "white_hits"
elif panel_render_mode in {"fade", "ambient"}:
    render_mode = "static"
elif panel_render_mode in {"bloom", "breath"}:
    render_mode = "morph"
else:
    render_mode = "dual_cycle" if structure in (MusicStructure.DROP, MusicStructure.BUILDUP) else "static"


# In ILDAOutputNode._frame_for_fixture():
mode_bias = _fixture_mode_bias(dynamics.get("fixture_mode", ""))
points = self._build_points(
    point_count=max(24, self.config.points_per_frame),
    geometry_family=geometry_family,
    color_mode=color_mode,
    target_bias=target_bias,
    beat_phase=beat_phase,
    bpm=bpm,
    timestamp=timestamp,
    harmonic_change=audio["harmonic_change"],
    pitch_height=audio["pitch_height"],
    melodic_contour=audio["melodic_contour"],
    melodic_stability=audio["melodic_stability"],
    onset_density=audio["onset_density"],
    harmonic_tension=audio["harmonic_tension"],
    harshness=audio["timbral_harshness"],
    color_drive=director["color_drive"],
    aggression=director["laser_aggression"],
    melodic_smoothness=director["melodic_smoothness"],
    motion_energy=director["laser_motion_energy"],
    color_energy=director["laser_color_energy"],
    motion_multiplier=dynamics["motion_multiplier"] * mode_bias["motion"],
    intensity_multiplier=dynamics["intensity_multiplier"] * mode_bias["intensity"],
    strobe_level=strobe_level * mode_bias["strobe"],
    program_look=program_look,
    palette=palette,
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_fixture_control.py -k "panel_prefers_led_pattern_when_panel_family_is_unknown or panel_uses_wash_pattern_when_panel_family_is_wash or fixture_mode_peak_return_biases_panel_and_mover_output" -v`

Run: `pytest tests/unit/test_ilda_output.py -k "fixture_mode_intro_reduces_motion_posture" -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/photonic_synesthesia/graph/nodes/fixture_control.py src/photonic_synesthesia/graph/nodes/ilda_output.py tests/unit/test_fixture_control.py tests/unit/test_ilda_output.py
git commit -m "feat: honor fixture mode and panel patterns at runtime"
```

## Task 5: Preserve Existing Field Contracts And Run The Focused Regression Sweep

**Files:**
- Test: `tests/unit/test_web_panel.py`
- Test: `tests/unit/test_runtime_context_helpers.py`

- [ ] **Step 1: Write the failing regression tests**

```python
def test_show_section_patch_keeps_fixture_mode_field_name(client_with_session) -> None:
    client, playback = client_with_session
    playback._replace_show_sections_locked([
        {
            "id": "section_001",
            "label": "Intro",
            "start_seconds": 0.0,
            "end_seconds": 16.0,
            "scene_id": "intro_ambient",
            "fixture_mode": "intro",
            "laser_pattern": "fan",
            "mover_pattern": "drift",
            "wash_pattern": "ambient",
            "led_pattern": "pulse",
        }
    ])

    response = client.patch(
        "/api/mock/playback/show-sections/section_001",
        json={"changes": {"fixture_mode": "peak_return", "laser_pattern": "wave"}},
    )

    assert response.status_code == 200
    assert response.json()["show_sections"][0]["fixture_mode"] == "peak_return"
    assert response.json()["show_sections"][0]["laser_pattern"] == "wave"


def test_snapshot_active_scene_id_overlay_semantics_remain_playhead_derived() -> None:
    ctx = PlaybackContext(
        file_path="/tmp/track.mp3",
        file_name="track.mp3",
        duration_seconds=20.0,
        show_sections=[
            {"id": "sec-0", "start_seconds": 0.0, "end_seconds": 10.0, "scene_id": "intro_ambient"},
            {"id": "sec-1", "start_seconds": 10.0, "end_seconds": 20.0, "scene_id": "drop_intense"},
        ],
    )
    ctx.update_transport(playhead_seconds=12.0, playing=True, finished=False, realtime=True, speed=1.0)

    snap = ctx.snapshot()

    assert snap["active_scene_id"] == "sec-1"
```

- [ ] **Step 2: Run tests to verify they fail only if contract drift was introduced**

Run: `pytest tests/unit/test_web_panel.py -k "keeps_fixture_mode_field_name" -v`

Run: `pytest tests/unit/test_runtime_context_helpers.py -k "active_scene_id" -v`

Expected: The web-panel regression may already PASS; if so, keep it as a guard and proceed. The runtime-context helper tests should PASS unchanged. Do not modify production code for this task unless a prior implementation step broke the existing field-name or overlay contract.

- [ ] **Step 3: Keep production code unchanged unless a prior task broke the contract**

```python
# No new production implementation is expected in this task.
# If the new runtime wiring accidentally changed field names or overlay
# semantics, fix the responsible earlier file rather than adding a
# compatibility shim here.
```

- [ ] **Step 4: Run the focused regression sweep**

Run: `pytest tests/unit/test_runtime_nodes.py -v`

Run: `pytest tests/unit/test_scene_select.py -v`

Run: `pytest tests/unit/test_fixture_control.py -v`

Run: `pytest tests/unit/test_ilda_output.py -v`

Run: `pytest tests/unit/test_web_panel.py -k "fixture_mode or laser_pattern or active_scene_id" -v`

Run: `pytest tests/unit/test_runtime_context_helpers.py -k "active_scene_id" -v`

Run: `pytest tests/unit/test_runtime_nodes.py tests/unit/test_scene_select.py tests/unit/test_fixture_control.py tests/unit/test_ilda_output.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_web_panel.py tests/unit/test_runtime_context_helpers.py
git commit -m "test: lock runtime override field contracts"
```
