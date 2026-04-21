# Live Section Dynamics Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make approved section-editor performance controls affect live runtime output by wiring section dynamics into the active DMX and ILDA emitters without changing the existing API or show-plan schema.

**Architecture:** Add one shared helper that resolves the active authored section from `playback_snapshot` and normalizes the live dynamics payload each tick. Then thread that payload into the runtime consumers that actually emit fixture commands and ILDA frames, using family-enable flags as hard gates and applying section-local intensity, motion, and strobe modifiers inside the family emitters while leaving control-plane intensity, blackout, arming, and safety interlocks authoritative.

**Tech Stack:** Python 3, existing graph node pipeline, `PlaybackContext` snapshots, FastAPI-backed runtime state, pytest.

---

## File Structure

### New files

- `src/photonic_synesthesia/graph/nodes/section_dynamics.py`
  - Shared active-section lookup and normalization helper used by runtime nodes.

### Modified files

- `src/photonic_synesthesia/graph/nodes/fixture_control.py`
  - Wire section dynamics into `LaserControlNode`, `MovingHeadControlNode`, and `PanelControlNode`.
- `src/photonic_synesthesia/graph/nodes/ilda_output.py`
  - Wire section dynamics into live ILDA frame generation and laser blackout behavior.
- `tests/unit/test_runtime_nodes.py`
  - Unit coverage for active-section selection, normalization, and panel-family inference.
- `tests/unit/test_fixture_control.py`
  - Live DMX behavior coverage for mover, panel, and DMX-laser gating/modulation.
- `tests/unit/test_ilda_output.py`
  - Live ILDA behavior coverage for laser gating, intensity scaling, motion scaling, and strobe suppression.

## Scope Notes

- The approved slice is `intensity_multiplier`, `motion_multiplier`, `strobe_level`, `laser_enabled`, `movers_enabled`, `washes_enabled`, and `leds_enabled`.
- `scene_id`, `fixture_mode`, `laser_pattern`, `mover_pattern`, `wash_pattern`, and `led_pattern` remain deferred.
- The generic DMX laser adapter profiles currently expose movement, pattern, and zoom controls but no verified dimmer or strobe channel. Do not fake laser intensity/strobe there. Wire hard enable plus motion on the DMX laser path, and when a section disables lasers, actively neutralize only the mapped DMX laser channels so the previous universe does not remain latched. Wire laser intensity/strobe on the primary ILDA path where color amplitude and blanking are real expressive outputs.
- `PanelControlNode` is the only runtime consumer for `FixtureConfig(type="panel")`, so the helper should infer a current panel family (`"wash"`, `"led"`, or `None`) from `lead_family` / `fixture_role_map` and fall back to `washes_enabled or leds_enabled` when the authored section does not clearly distinguish them.

## Task 1: Add Shared Active-Section Dynamics Resolver

**Files:**
- Create: `src/photonic_synesthesia/graph/nodes/section_dynamics.py`
- Test: `tests/unit/test_runtime_nodes.py`

- [ ] **Step 1: Write the failing test**

```python
from photonic_synesthesia.core.state import create_initial_state
from photonic_synesthesia.graph.nodes.section_dynamics import resolve_active_section_dynamics


def test_resolve_active_section_dynamics_defaults_without_snapshot() -> None:
    dynamics = resolve_active_section_dynamics(create_initial_state())

    assert dynamics["intensity_multiplier"] == 1.0
    assert dynamics["motion_multiplier"] == 1.0
    assert dynamics["strobe_level"] == 0.0
    assert dynamics["laser_enabled"] is True
    assert dynamics["movers_enabled"] is True
    assert dynamics["washes_enabled"] is True
    assert dynamics["leds_enabled"] is True
    assert dynamics["panel_family"] is None


def test_resolve_active_section_dynamics_selects_current_section_and_infers_panel_family() -> None:
    state = create_initial_state()
    state["playback_snapshot"] = {
        "playhead_seconds": 14.0,
        "show_sections": [
            {
                "id": "sec-1",
                "start_seconds": 0.0,
                "end_seconds": 8.0,
                "intensity_multiplier": 0.6,
                "washes_enabled": True,
                "leds_enabled": True,
            },
            {
                "id": "sec-2",
                "start_seconds": 8.0,
                "end_seconds": 20.0,
                "lead_family": "wash",
                "intensity_multiplier": 0.75,
                "motion_multiplier": 1.3,
                "strobe_level": 0.4,
                "laser_enabled": False,
                "movers_enabled": True,
                "washes_enabled": False,
                "leds_enabled": True,
                "fixture_role_map": {"wash": {"role": "hero"}, "led": {"role": "support"}},
            },
        ],
    }

    dynamics = resolve_active_section_dynamics(state)

    assert dynamics["section_id"] == "sec-2"
    assert dynamics["intensity_multiplier"] == 0.75
    assert dynamics["motion_multiplier"] == 1.3
    assert dynamics["strobe_level"] == 0.4
    assert dynamics["laser_enabled"] is False
    assert dynamics["washes_enabled"] is False
    assert dynamics["panel_family"] == "wash"


def test_resolve_active_section_dynamics_uses_last_section_and_coerces_invalid_values() -> None:
    state = create_initial_state()
    state["playback_snapshot"] = {
        "playhead_seconds": 99.0,
        "show_sections": [
            {
                "id": "sec-last",
                "start_seconds": 2.0,
                "end_seconds": 10.0,
                "intensity_multiplier": "bad",
                "motion_multiplier": None,
                "strobe_level": "nan-ish",
                "laser_enabled": 0,
                "movers_enabled": "yes",
                "washes_enabled": None,
                "leds_enabled": 1,
                "fixture_role_map": {"led": {"role": "hero"}},
            }
        ],
    }

    dynamics = resolve_active_section_dynamics(state)

    assert dynamics["section_id"] == "sec-last"
    assert dynamics["intensity_multiplier"] == 1.0
    assert dynamics["motion_multiplier"] == 1.0
    assert dynamics["strobe_level"] == 0.0
    assert dynamics["laser_enabled"] is False
    assert dynamics["movers_enabled"] is True
    assert dynamics["washes_enabled"] is True
    assert dynamics["leds_enabled"] is True
    assert dynamics["panel_family"] == "led"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_runtime_nodes.py -k "section_dynamics" -v`

Expected: FAIL with `ModuleNotFoundError` for `photonic_synesthesia.graph.nodes.section_dynamics`.

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

from typing import Any, Literal, TypedDict

from photonic_synesthesia.core.state import PhotonicState
from photonic_synesthesia.platform.runtime_context import get_shared_playback_context


class SectionDynamics(TypedDict):
    section_id: str | None
    current_section: dict[str, Any] | None
    intensity_multiplier: float
    motion_multiplier: float
    strobe_level: float
    laser_enabled: bool
    movers_enabled: bool
    washes_enabled: bool
    leds_enabled: bool
    panel_family: Literal["wash", "led"] | None


def _float_or_default(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bool_or_default(value: Any, default: bool) -> bool:
    if value is None:
        return default
    return bool(value)


def _snapshot_for_state(state: PhotonicState) -> dict[str, Any]:
    snapshot = dict(state.get("playback_snapshot") or {})
    if snapshot:
        return snapshot
    playback = get_shared_playback_context()
    if playback is None:
        return {}
    return playback.snapshot()


def _active_section(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    sections = snapshot.get("show_sections") or []
    if not sections:
        return None
    playhead = _float_or_default(snapshot.get("playhead_seconds"), 0.0)
    for section in sections:
        start = _float_or_default(section.get("start_seconds"), 0.0)
        end = _float_or_default(section.get("end_seconds"), start)
        if start <= playhead < max(end, start + 1e-6):
            return section
    return sections[-1]


def _panel_family(section: dict[str, Any] | None) -> Literal["wash", "led"] | None:
    if not isinstance(section, dict):
        return None
    lead_family = str(section.get("lead_family") or "")
    if lead_family in {"wash", "led"}:
        return lead_family
    fixture_role_map = dict(section.get("fixture_role_map") or {})
    has_wash = isinstance(fixture_role_map.get("wash"), dict)
    has_led = isinstance(fixture_role_map.get("led"), dict)
    if has_wash and not has_led:
        return "wash"
    if has_led and not has_wash:
        return "led"
    return None


def resolve_active_section_dynamics(state: PhotonicState) -> SectionDynamics:
    section = _active_section(_snapshot_for_state(state))
    return SectionDynamics(
        section_id=str(section.get("id")) if isinstance(section, dict) and section.get("id") else None,
        current_section=section,
        intensity_multiplier=_float_or_default(section.get("intensity_multiplier") if isinstance(section, dict) else None, 1.0),
        motion_multiplier=_float_or_default(section.get("motion_multiplier") if isinstance(section, dict) else None, 1.0),
        strobe_level=_float_or_default(section.get("strobe_level") if isinstance(section, dict) else None, 0.0),
        laser_enabled=_bool_or_default(section.get("laser_enabled") if isinstance(section, dict) else None, True),
        movers_enabled=_bool_or_default(section.get("movers_enabled") if isinstance(section, dict) else None, True),
        washes_enabled=_bool_or_default(section.get("washes_enabled") if isinstance(section, dict) else None, True),
        leds_enabled=_bool_or_default(section.get("leds_enabled") if isinstance(section, dict) else None, True),
        panel_family=_panel_family(section),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_runtime_nodes.py -k "section_dynamics" -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/photonic_synesthesia/graph/nodes/section_dynamics.py tests/unit/test_runtime_nodes.py
git commit -m "feat: add active section dynamics resolver"
```

## Task 2: Wire Laser Section Dynamics Into DMX and ILDA Paths

**Files:**
- Modify: `src/photonic_synesthesia/graph/nodes/fixture_control.py`
- Modify: `src/photonic_synesthesia/graph/nodes/ilda_output.py`
- Test: `tests/unit/test_fixture_control.py`
- Test: `tests/unit/test_ilda_output.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from photonic_synesthesia.core.config import FixtureConfig, ILDAConfig, LaserSafetyConfig
from photonic_synesthesia.core.state import MusicStructure, create_initial_state
from photonic_synesthesia.graph.nodes.fixture_control import LaserControlNode
from photonic_synesthesia.graph.nodes.ilda_output import ILDAOutputNode
from photonic_synesthesia.platform.runtime_context import (
    PlaybackContext,
    clear_shared_playback_context,
    set_shared_playback_context,
)


def test_laser_control_clears_dmx_universe_when_active_section_disables_lasers() -> None:
    fixture = FixtureConfig(
        id="laser-main",
        name="Main Laser",
        type="laser",
        profile="laser_generic_7ch",
        start_address=1,
        enabled=True,
    )
    node = LaserControlNode([fixture], LaserSafetyConfig(y_axis_max=96), fixtures_dir=Path("config/fixtures"))
    playback = set_shared_playback_context(
        PlaybackContext(
            file_path="/tmp/track.mp3",
            file_name="track.mp3",
            duration_seconds=30.0,
            show_sections=[{
                "id": "section_000",
                "start_seconds": 0.0,
                "end_seconds": 30.0,
                "laser_enabled": False,
                "motion_multiplier": 1.6,
            }],
        )
    )
    playback.update_transport(playhead_seconds=4.0, playing=True, finished=False, realtime=True, speed=1.0)

    state = create_initial_state()
    state["current_structure"] = MusicStructure.DROP
    state["fused_bpm"] = 128.0
    state["audio_features"]["rms_energy"] = 0.75
    state["control_state"]["armed_live"] = True

    enabled_state = create_initial_state()
    enabled_state["current_structure"] = MusicStructure.DROP
    enabled_state["fused_bpm"] = 128.0
    enabled_state["audio_features"]["rms_energy"] = 0.75
    enabled_state["control_state"]["armed_live"] = True

    disabled_state = create_initial_state()
    disabled_state["current_structure"] = MusicStructure.DROP
    disabled_state["fused_bpm"] = 128.0
    disabled_state["audio_features"]["rms_energy"] = 0.75
    disabled_state["control_state"]["armed_live"] = True

    try:
        playback.update_transport(playhead_seconds=1.0, playing=True, finished=False, realtime=True, speed=1.0)
        enabled_result = node(enabled_state)
        playback.update_show_sections([
            {
                "id": "section_000",
                "start_seconds": 0.0,
                "end_seconds": 30.0,
                "laser_enabled": False,
                "motion_multiplier": 1.6,
            }
        ])
        playback.update_transport(playhead_seconds=4.0, playing=True, finished=False, realtime=True, speed=1.0)
        disabled_result = node(disabled_state)
    finally:
        clear_shared_playback_context()

    assert enabled_result["fixture_commands"], "precondition: enabled section must emit laser commands"
    assert disabled_result["fixture_commands"], "disabled section must emit a neutralizing command, not silence"
    disabled_channels = disabled_result["fixture_commands"][0]["channel_values"]
    assert all(value == 0 for value in disabled_channels.values())


def test_ilda_output_uses_section_intensity_motion_and_strobe() -> None:
    fixture = FixtureConfig(
        id="laser-main",
        name="Main Laser",
        type="laser",
        profile="laser_aucd_cx338b_hybrid",
        start_address=1,
        enabled=True,
    )
    node = ILDAOutputNode(
        ILDAConfig(enabled=True, points_per_frame=32),
        [fixture],
        LaserSafetyConfig(y_axis_max=96),
        fixtures_dir=Path("config/fixtures"),
    )
    playback = set_shared_playback_context(
        PlaybackContext(
            file_path="/tmp/track.mp3",
            file_name="track.mp3",
            duration_seconds=32.0,
            show_sections=[{
                "id": "section_000",
                "start_seconds": 0.0,
                "end_seconds": 32.0,
                "laser_enabled": True,
                "intensity_multiplier": 0.35,
                "motion_multiplier": 1.6,
                "strobe_level": 0.0,
                "laser_program": {
                    "phrase_role": "drop_variation",
                    "zone_policy": "overhead_only",
                    "fill_trigger_every_bars": 4,
                    "launch": {"pattern": "sheet", "geometry_family": "sheet", "bars": 2},
                    "sustain": [{"pattern": "burst", "geometry_family": "burst", "color_mode": "white_hits", "bars": 8}],
                    "fills": [],
                    "release": {"pattern": "trace", "geometry_family": "trace", "bars": 2},
                },
            }],
        )
    )
    playback.update_transport(playhead_seconds=10.0, playing=True, finished=False, realtime=True, speed=1.0)

    state = create_initial_state()
    state["control_state"]["armed_live"] = True
    state["current_structure"] = MusicStructure.DROP
    state["fused_bpm"] = 128.0
    state["beat_info"]["beat_phase"] = 0.05
    state["audio_features"]["timbral_harshness"] = 0.85
    state["director_state"]["laser_aggression"] = 0.9
    state["director_state"]["laser_motion_energy"] = 0.8
    state["director_state"]["color_drive"] = 0.7

    try:
        frame = node(state)["ilda_frames"][0]
    finally:
        clear_shared_playback_context()

    lit_points = [point for point in frame["points"] if not point["blanked"]]
    assert lit_points, "section should still emit non-blank ILDA points"
    assert max(point["r"] for point in lit_points) < 255
    assert all(point["blanked"] is False for point in frame["points"][::6])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_fixture_control.py -k "clears_dmx_universe_when_active_section_disables_lasers" -v`

Expected: FAIL because `LaserControlNode` either leaves the previous DMX universe latched or emits no command at all when `laser_enabled` is false.

Run: `pytest tests/unit/test_ilda_output.py -k "section_intensity_motion_and_strobe" -v`

Expected: FAIL because `ILDAOutputNode` ignores section dynamics and still emits full-intensity / strobe-biased frames.

- [ ] **Step 3: Write minimal implementation**

In `src/photonic_synesthesia/graph/nodes/fixture_control.py`, import the helper and gate the DMX laser path:

```python
from photonic_synesthesia.graph.nodes.section_dynamics import resolve_active_section_dynamics


def __call__(self, state: PhotonicState) -> PhotonicState:
    start_time = time.time()
    if not self.fixtures:
        return state

    dynamics = resolve_active_section_dynamics(state)
    scene = state["scene_state"]["current_scene"]
    structure = state["current_structure"]
    beat_phase = state["beat_info"]["beat_phase"]
    bpm = state["fused_bpm"]
    energy = state["audio_features"]["rms_energy"]
    low_energy = state["audio_features"]["low_energy"]

    for fixture in self.fixtures:
        if not fixture.enabled:
            continue
        if not dynamics["laser_enabled"]:
            state["fixture_commands"].append(self._generate_disabled_laser_commands(fixture))
            continue
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
        )
        state["fixture_commands"].append(commands)
```

Add the neutral-command helper and thread the motion multiplier through `_generate_laser_commands`:

```python
def _generate_disabled_laser_commands(self, fixture: FixtureConfig) -> FixtureCommand:
    base = fixture.start_address
    values: dict[int, int] = {}
    profile = self.fixture_profiles.get(fixture.id)
    channel_map = profile.channel_map if profile is not None else {}
    for channel_offset in channel_map.values():
        values[base + channel_offset] = 0
    return FixtureCommand(
        fixture_id=fixture.id,
        fixture_type="laser",
        channel_values=values,
    )


def _generate_laser_commands(
    self,
    fixture: FixtureConfig,
    scene: str,
    structure: MusicStructure,
    beat_phase: float,
    bpm: float,
    energy: float,
    low_energy: float,
    current_time: float,
    *,
    motion_multiplier: float,
) -> FixtureCommand:
    motion_gain = max(0.25, min(2.0, motion_multiplier))
    x_pos = int(128 + 100 * position_scale * math.sin(current_time * bpm / 60 * motion_gain))
    y_pos = int(64 + 30 * position_scale * math.sin(current_time * bpm / 120 * motion_gain))
    scan_speed = max(scan_speed, self.safety.min_scan_speed)
    pattern_speed = max(0, min(255, int(pattern_speed * (0.6 + motion_gain * 0.4))))
```

In `src/photonic_synesthesia/graph/nodes/ilda_output.py`, resolve the same helper once per tick and pass the normalized values into `_build_points`:

```python
from photonic_synesthesia.graph.nodes.section_dynamics import resolve_active_section_dynamics


def _frame_for_fixture(self, fixture: FixtureConfig, state: PhotonicState) -> ILDAFrame:
    dynamics = resolve_active_section_dynamics(state)
    if not dynamics["laser_enabled"]:
        return self._blank_frame_for_fixture(fixture)

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
        intensity_multiplier=dynamics["intensity_multiplier"],
        motion_multiplier=dynamics["motion_multiplier"],
        strobe_level=dynamics["strobe_level"],
        program_look=program_look,
        palette=palette,
    )
```

Then apply the modifiers inside `_build_points`. Keep the existing geometry-family branch structure, but replace the setup plus the color/blanking block with these exact lines:

```python
def _build_points(
    self,
    *,
    point_count: int,
    geometry_family: str,
    color_mode: str,
    target_bias: str,
    beat_phase: float,
    bpm: float,
    timestamp: float,
    harmonic_change: float,
    pitch_height: float,
    melodic_contour: float,
    melodic_stability: float,
    onset_density: float,
    harmonic_tension: float,
    harshness: float,
    color_drive: float,
    aggression: float,
    melodic_smoothness: float,
    motion_energy: float,
    color_energy: float,
    intensity_multiplier: float,
    motion_multiplier: float,
    strobe_level: float,
    program_look: dict[str, Any] | None,
    palette: Palette = DEFAULT_PALETTE,
) -> list[ILDAPoint]:
    motion_gain = max(0.25, min(2.0, motion_multiplier))
    intensity_gain = max(0.0, min(1.5, intensity_multiplier))
    strobe_gain = max(0.0, min(1.0, strobe_level))
    density_scale = float(program_look.get("density", 1.0)) if program_look else 1.0
    look_motion_scale = float(program_look.get("motion", 1.0)) if program_look else 1.0
    effective_motion = max(0.25, min(2.5, look_motion_scale * motion_gain))
    sweep_phase = timestamp * max(0.25, bpm / 60.0) * (0.5 + aggression * 1.8) * effective_motion
    amplitude_x = (0.35 + aggression * 0.45) * (0.78 + look_motion_scale * 0.34) * (0.86 + motion_energy * 0.28)
    amplitude_y = min(
        self.safety.y_axis_max / 255.0,
        (0.12 + melodic_smoothness * 0.28 + pitch_height * 0.18 + (melodic_contour - 0.5) * 0.08)
        * (0.82 + look_motion_scale * 0.22),
    )
    amplitude_x *= 0.75 + motion_gain * 0.25
    amplitude_y *= 0.8 + motion_gain * 0.2
    beat_boost = 1.0 + (0.18 + onset_density * 0.18) * math.sin(beat_phase * math.pi * 2.0)
    points: list[ILDAPoint] = []
    for index in range(point_count):
        t = index / max(1, point_count - 1)
        shape_phase = sweep_phase + t * math.pi * 2.0
        if geometry_family == "fan":
            x = math.sin(shape_phase) * amplitude_x * beat_boost
            y = y_offset + math.cos(shape_phase * 0.5) * amplitude_y
        elif geometry_family == "burst":
            radial = (0.15 + 0.85 * t) * beat_boost
            x = math.sin(shape_phase * 1.8) * amplitude_x * radial
            y = y_offset + math.cos(shape_phase * 1.1) * amplitude_y * radial
        else:
            x = math.sin(shape_phase * 0.7) * amplitude_x * 0.75
            y = y_offset + abs(math.sin(shape_phase * 0.9)) * amplitude_y

        color_phase = shape_phase + harmonic_change * 5.0 + color_energy * 2.0
        r, g, b = _rgb_from_mode(
            color_mode,
            color_phase,
            color_drive + color_energy * 0.25,
            harshness,
            palette=palette,
        )
        r = int(round(r * intensity_gain))
        g = int(round(g * intensity_gain))
        b = int(round(b * intensity_gain))

        blanked = False
        blanking_density = max(1, int(round(8 - min(6, density_scale * 3.2))))
        if geometry_family == "burst" and aggression > 0.72 and strobe_gain > 0.01:
            blanked = (index % max(3, 7 - int(round(strobe_gain * 3)))) in {0, 1} and beat_phase < 0.22
        elif geometry_family == "sequence":
            blanked = strobe_gain > 0.01 and (index % blanking_density) != int((beat_phase * blanking_density) % blanking_density)
        elif geometry_family == "sheet":
            blanked = density_scale < 0.9 and (index % max(2, blanking_density - 2)) == 0
        elif harshness > 0.78 and strobe_gain > 0.01:
            blanked = (index % 7) == 0 and math.sin(shape_phase * 2.0) > 0.0

        points.append(
            ILDAPoint(
                x=_clamp_coord(x * _ILDA_MAX),
                y=_clamp_coord(y * _ILDA_MAX),
                r=0 if blanked else r,
                g=0 if blanked else g,
                b=0 if blanked else b,
                blanked=blanked,
            )
        )
    return points
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_fixture_control.py -k "clears_dmx_universe_when_active_section_disables_lasers" -v`

Expected: PASS

Run: `pytest tests/unit/test_ilda_output.py -k "section_intensity_motion_and_strobe" -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/photonic_synesthesia/graph/nodes/fixture_control.py src/photonic_synesthesia/graph/nodes/ilda_output.py tests/unit/test_fixture_control.py tests/unit/test_ilda_output.py
git commit -m "feat: wire section dynamics into laser runtime paths"
```

## Task 3: Wire Moving-Head Section Dynamics

**Files:**
- Modify: `src/photonic_synesthesia/graph/nodes/fixture_control.py`
- Test: `tests/unit/test_fixture_control.py`

- [ ] **Step 1: Write the failing test**

```python
from photonic_synesthesia.core.config import MovingHeadSafetyConfig
from photonic_synesthesia.core.state import MusicStructure, create_initial_state
from photonic_synesthesia.graph.nodes.fixture_control import MovingHeadControlNode
from photonic_synesthesia.platform.runtime_context import (
    PlaybackContext,
    clear_shared_playback_context,
    set_shared_playback_context,
)


def test_moving_head_control_respects_movers_enabled_flag() -> None:
    node = MovingHeadControlNode([_moving_head_fixture()], MovingHeadSafetyConfig())
    playback = set_shared_playback_context(
        PlaybackContext(
            file_path="/tmp/track.mp3",
            file_name="track.mp3",
            duration_seconds=16.0,
            show_sections=[{
                "id": "section_000",
                "start_seconds": 0.0,
                "end_seconds": 16.0,
                "movers_enabled": False,
                "intensity_multiplier": 1.0,
                "motion_multiplier": 1.0,
                "strobe_level": 1.0,
            }],
        )
    )
    playback.update_transport(playhead_seconds=4.0, playing=True, finished=False, realtime=True, speed=1.0)

    state = create_initial_state()
    state["current_structure"] = MusicStructure.DROP
    state["beat_info"]["beat_phase"] = 0.05
    state["fused_bpm"] = 128.0
    state["audio_features"]["rms_energy"] = 0.8

    try:
        result = node(state)
    finally:
        clear_shared_playback_context()

    assert result["fixture_commands"] == []


def test_moving_head_control_scales_motion_intensity_and_strobe_from_section() -> None:
    node = MovingHeadControlNode([_moving_head_fixture()], MovingHeadSafetyConfig())
    playback = set_shared_playback_context(
        PlaybackContext(
            file_path="/tmp/track.mp3",
            file_name="track.mp3",
            duration_seconds=16.0,
            show_sections=[{
                "id": "section_000",
                "start_seconds": 0.0,
                "end_seconds": 16.0,
                "movers_enabled": True,
                "intensity_multiplier": 0.5,
                "motion_multiplier": 1.7,
                "strobe_level": 0.0,
                "laser_program": {
                    "phrase_role": "drop_variation",
                    "zone_policy": "crowd_punctuate",
                    "fill_trigger_every_bars": 4,
                    "launch": {"pattern": "fan", "geometry_family": "fan", "bars": 2},
                    "sustain": [{"pattern": "burst_fan", "geometry_family": "burst", "motion": 1.2, "bars": 8}],
                    "fills": [],
                    "release": {"pattern": "trace", "geometry_family": "trace", "bars": 2},
                },
            }],
        )
    )
    playback.update_transport(playhead_seconds=6.0, playing=True, finished=False, realtime=True, speed=1.0)

    state = create_initial_state()
    state["current_structure"] = MusicStructure.DROP
    state["beat_info"]["beat_phase"] = 0.03
    state["beat_info"]["bar_position"] = 1
    state["fused_bpm"] = 128.0
    state["audio_features"]["rms_energy"] = 0.82
    state["director_state"]["subphrase_role"] = "fill"

    try:
        command = node(state)["fixture_commands"][0]["channel_values"]
    finally:
        clear_shared_playback_context()

    assert command[1 + node.channel_map["dimmer"]] < 200
    assert command[1 + node.channel_map["strobe"]] == 0
    assert abs(command[1 + node.channel_map["pan"]] - 128) > 40
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_fixture_control.py -k "movers_enabled_flag or scales_motion_intensity_and_strobe_from_section" -v`

Expected: FAIL because `MovingHeadControlNode` ignores `movers_enabled`, `intensity_multiplier`, `motion_multiplier`, and `strobe_level`.

- [ ] **Step 3: Write minimal implementation**

In `src/photonic_synesthesia/graph/nodes/fixture_control.py`, replace `MovingHeadControlNode.__call__` with this version so section dynamics are resolved once per tick and applied to every fixture in the loop:

```python
def __call__(self, state: PhotonicState) -> PhotonicState:
    start_time = time.time()
    if not self.fixtures:
        return state

    dynamics = resolve_active_section_dynamics(state)
    if not dynamics["movers_enabled"]:
        state["processing_times"]["moving_head_control"] = time.time() - start_time
        return state

    scene = state["scene_state"]["current_scene"]
    structure = state["current_structure"]
    beat_phase = state["beat_info"]["beat_phase"]
    bar_position = state["beat_info"]["bar_position"]
    bpm = state["fused_bpm"]
    energy = state["audio_features"]["rms_energy"]
    program_look = self._current_program_look(state)
    director_state = state["director_state"]
    palette = resolve_palette(str(director_state.get("color_theme") or "neutral"))
    color_drive = float(director_state.get("color_drive") or 0.5)

    for i, fixture in enumerate(self.fixtures):
        if not fixture.enabled:
            continue
        phase_offset = (i / len(self.fixtures)) * math.pi * 2
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
            strobe_level=dynamics["strobe_level"],
        )
        state["fixture_commands"].append(commands)

    state["processing_times"]["moving_head_control"] = time.time() - start_time
    return state
```

Then apply the local section modifiers inside `_generate_moving_head_commands`. Keep the existing structure-selection branches, but replace the modifier-sensitive lines with these exact expressions:

```python
def _generate_moving_head_commands(
    self,
    fixture: FixtureConfig,
    scene: str,
    structure: MusicStructure,
    beat_phase: float,
    bar_position: int,
    bpm: float,
    energy: float,
    current_time: float,
    phase_offset: float,
    *,
    program_look: dict[str, Any] | None = None,
    palette: Palette,
    color_drive: float,
    intensity_multiplier: float,
    motion_multiplier: float,
    strobe_level: float,
) -> FixtureCommand:
    motion_gain = max(0.25, min(2.0, motion_multiplier))
    intensity_gain = max(0.0, min(1.5, intensity_multiplier))
    strobe_gain = max(0.0, min(1.0, strobe_level))
    motion_phase = current_time * bpm / 60 * (0.7 + motion_scale * 0.9) * motion_gain + phase_offset
    pan_amp = (58 + motion_scale * 34 + emphasis * 18) * (0.8 + motion_gain * 0.2)
    tilt_amp = (34 + motion_scale * 18 + emphasis * 10) * (0.8 + motion_gain * 0.2)
    pan = int(128 + pan_amp * max(-1.0, min(1.0, pan_norm)))
    tilt = int(128 + tilt_amp * max(-1.0, min(1.0, tilt_norm)))
    values[base + self.channel_map["pan"]] = pan
    values[base + self.channel_map["tilt"]] = tilt

    if mover_family == "hits":
        speed = 218
    elif mover_family == "cross":
        speed = 188
    elif mover_family == "rise":
        speed = 168
    elif mover_family == "hold":
        speed = 96
    else:
        speed = 200 if structure == MusicStructure.DROP else 128
    values[base + self.channel_map["pan_tilt_speed"]] = min(255, int(speed * (0.7 + motion_gain * 0.3)))

    role_boost = {"launch": 26, "fill": 34, "release": -30}.get(look_role, 0)
    if structure == MusicStructure.DROP:
        dimmer = int(192 + 58 * energy + emphasis * 18 + role_boost)
    elif structure == MusicStructure.BREAKDOWN:
        dimmer = int(92 + 44 * energy + role_boost)
    else:
        dimmer = int(142 + 78 * energy + emphasis * 12 + role_boost)
    dimmer = int(dimmer * intensity_gain)
    values[base + self.channel_map["dimmer"]] = min(255, dimmer)

    if mover_family == "hits" and beat_hit > 0.0:
        strobe = 208
    elif look_role == "launch" and structure in {MusicStructure.DROP, MusicStructure.BUILDUP} and beat_hit > 0.0:
        strobe = 160
    else:
        strobe = 0
    if strobe_gain <= 0.01:
        strobe = 0
    elif strobe > 0:
        strobe = min(255, int(round(strobe * (0.45 + strobe_gain * 0.55))))
    values[base + self.channel_map["strobe"]] = strobe
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_fixture_control.py -k "movers_enabled_flag or scales_motion_intensity_and_strobe_from_section" -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/photonic_synesthesia/graph/nodes/fixture_control.py tests/unit/test_fixture_control.py
git commit -m "feat: wire section dynamics into moving head control"
```

## Task 4: Wire Panel Section Dynamics and Operator-Intent Live Regressions

**Files:**
- Modify: `src/photonic_synesthesia/graph/nodes/fixture_control.py`
- Test: `tests/unit/test_fixture_control.py`

- [ ] **Step 1: Write the failing test**

```python
from photonic_synesthesia.core.config import FixtureConfig
from photonic_synesthesia.core.state import MusicStructure, create_initial_state
from photonic_synesthesia.graph.nodes.fixture_control import PanelControlNode
from photonic_synesthesia.platform.runtime_context import (
    PlaybackContext,
    clear_shared_playback_context,
    set_shared_playback_context,
)


def _panel_fixture() -> FixtureConfig:
    return FixtureConfig(
        id="panel-main",
        name="Panel Main",
        type="panel",
        profile="generic_panel",
        start_address=1,
        enabled=True,
    )


def test_panel_control_uses_inferred_panel_family_for_enable_gate() -> None:
    node = PanelControlNode([_panel_fixture()])
    playback = set_shared_playback_context(
        PlaybackContext(
            file_path="/tmp/track.mp3",
            file_name="track.mp3",
            duration_seconds=12.0,
            show_sections=[{
                "id": "section_000",
                "start_seconds": 0.0,
                "end_seconds": 12.0,
                "lead_family": "wash",
                "washes_enabled": False,
                "leds_enabled": True,
                "fixture_role_map": {"wash": {"role": "hero"}, "led": {"role": "support"}},
            }],
        )
    )
    playback.update_transport(playhead_seconds=2.0, playing=True, finished=False, realtime=True, speed=1.0)

    state = create_initial_state()
    state["current_structure"] = MusicStructure.DROP
    state["beat_info"]["beat_phase"] = 0.02
    state["beat_info"]["bar_position"] = 1
    state["audio_features"]["rms_energy"] = 0.8

    try:
        result = node(state)
    finally:
        clear_shared_playback_context()

    assert result["fixture_commands"] == []


def test_panel_control_applies_section_dynamics_after_operator_intents() -> None:
    node = PanelControlNode([_panel_fixture()])
    playback = set_shared_playback_context(
        PlaybackContext(
            file_path="/tmp/track.mp3",
            file_name="track.mp3",
            duration_seconds=12.0,
            show_sections=[{
                "id": "section_000",
                "start_seconds": 0.0,
                "end_seconds": 12.0,
                "lead_family": "led",
                "washes_enabled": True,
                "leds_enabled": True,
                "intensity_multiplier": 1.0,
                "motion_multiplier": 1.0,
                "strobe_level": 0.8,
                "fixture_role_map": {"led": {"role": "hero"}},
            }],
        )
    )
    playback.apply_operator_intent(intent="darken", scope="track", target="all", amount=0.4)
    playback.apply_operator_intent(intent="less_strobe", scope="track", target="strobes", amount=1.0)
    playback.update_transport(playhead_seconds=2.0, playing=True, finished=False, realtime=True, speed=1.0)

    state = create_initial_state()
    state["current_structure"] = MusicStructure.DROP
    state["beat_info"]["beat_phase"] = 0.02
    state["beat_info"]["bar_position"] = 1
    state["audio_features"]["rms_energy"] = 0.8
    state["director_state"]["strobe_budget_hz"] = 8.0

    try:
        command = node(state)["fixture_commands"][0]["channel_values"]
    finally:
        clear_shared_playback_context()

    assert command[1 + node.channel_map["dimmer"]] < 200
    assert command[1 + node.channel_map["strobe"]] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_fixture_control.py -k "panel_family_for_enable_gate or panel_control_applies_section_dynamics_after_operator_intents" -v`

Expected: FAIL because `PanelControlNode` ignores section family-enable flags and does not consume section intensity/motion/strobe values.

- [ ] **Step 3: Write minimal implementation**

In `src/photonic_synesthesia/graph/nodes/fixture_control.py`, replace `PanelControlNode.__call__` with this version so the node derives one panel-family gate per tick and reuses it for every fixture:

```python
def __call__(self, state: PhotonicState) -> PhotonicState:
    start_time = time.time()
    if not self.fixtures:
        return state

    dynamics = resolve_active_section_dynamics(state)
    panel_enabled = (
        dynamics["washes_enabled"] if dynamics["panel_family"] == "wash"
        else dynamics["leds_enabled"] if dynamics["panel_family"] == "led"
        else dynamics["washes_enabled"] or dynamics["leds_enabled"]
    )
    if not panel_enabled:
        state["processing_times"]["panel_control"] = time.time() - start_time
        return state

    structure = state["current_structure"]
    beat_phase = state["beat_info"]["beat_phase"]
    bar_position = state["beat_info"]["bar_position"]
    energy = state["audio_features"]["rms_energy"]
    time_since_drop = state["time_since_last_drop"]
    director_state = state["director_state"]
    palette = resolve_palette(str(director_state.get("color_theme") or "neutral"))
    color_drive = float(director_state.get("color_drive") or 0.5)
    strobe_budget_hz = float(director_state.get("strobe_budget_hz") or 0.0)
    subphrase_role = str(director_state.get("subphrase_role") or "")

    for fixture in self.fixtures:
        if not fixture.enabled:
            continue
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
            intensity_multiplier=dynamics["intensity_multiplier"],
            motion_multiplier=dynamics["motion_multiplier"],
            strobe_level=dynamics["strobe_level"],
        )
        state["fixture_commands"].append(commands)

    state["processing_times"]["panel_control"] = time.time() - start_time
    return state
```

Then apply the section-local modifiers inside `_generate_panel_commands` by replacing the cadence, dimmer, and strobe expressions with these exact lines:

```python
def _generate_panel_commands(
    self,
    fixture: FixtureConfig,
    structure: MusicStructure,
    beat_phase: float,
    bar_position: int,
    energy: float,
    time_since_drop: float,
    current_time: float,
    *,
    palette: Palette,
    color_drive: float,
    strobe_budget_hz: float,
    subphrase_role: str,
    intensity_multiplier: float,
    motion_multiplier: float,
    strobe_level: float,
) -> FixtureCommand:
    motion_gain = max(0.25, min(2.0, motion_multiplier))
    intensity_gain = max(0.0, min(1.5, intensity_multiplier))
    strobe_gain = max(0.0, min(1.0, strobe_level))
    beats_per_cycle = (
        2.0 if structure in (MusicStructure.DROP, MusicStructure.BUILDUP) else 4.0
    ) / max(0.5, motion_gain)
    beat_clock = bar_position + beat_phase
    phase = (beat_clock / beats_per_cycle) * 2.0 * math.pi
    beat_hit = beat_phase < 0.15
    render_mode = (
        "dual_cycle"
        if structure in (MusicStructure.DROP, MusicStructure.BUILDUP)
        else "morph" if structure == MusicStructure.BREAKDOWN else "static"
    )
    rgb = render_rgb(
        palette,
        render_mode,
        phase=phase,
        beat_hit=beat_hit,
        color_drive=color_drive,
    )

    if structure == MusicStructure.DROP and subphrase_role == "launch" and time_since_drop < 0.9:
        dimmer = 255
        rgb = render_rgb(palette, "white_hits", phase=phase, beat_hit=True, color_drive=1.0)
    elif structure == MusicStructure.DROP:
        dimmer = int(200 + 55 * max(0.0, min(1.0, energy)))
    elif structure == MusicStructure.BUILDUP:
        dimmer = int(160 + 80 * max(0.0, min(1.0, energy)))
    elif structure == MusicStructure.BREAKDOWN:
        dimmer = int(90 + 60 * max(0.0, min(1.0, energy)))
    else:
        dimmer = int(60 + 120 * max(0.0, min(1.0, energy)))
    dimmer = int(dimmer * intensity_gain)
    values[base + self.channel_map["dimmer"]] = max(0, min(255, dimmer))
    if strobe_gain <= 0.01 or strobe_budget_hz < 0.6:
        strobe_value = 0
    else:
        strobe_ratio = max(0.0, min(1.0, (strobe_budget_hz / 12.0) * strobe_gain))
        strobe_value = int(16 + round(strobe_ratio * (240 - 16)))
    values[base + self.channel_map["strobe"]] = strobe_value
    values[base + self.channel_map["red"]] = rgb[0]
    values[base + self.channel_map["green"]] = rgb[1]
    values[base + self.channel_map["blue"]] = rgb[2]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_fixture_control.py -k "panel_family_for_enable_gate or panel_control_applies_section_dynamics_after_operator_intents" -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/photonic_synesthesia/graph/nodes/fixture_control.py tests/unit/test_fixture_control.py
git commit -m "feat: wire section dynamics into panel control"
```

## Task 5: Final Regression Sweep

**Files:**
- Modify: none
- Test: `tests/unit/test_runtime_nodes.py`
- Test: `tests/unit/test_fixture_control.py`
- Test: `tests/unit/test_ilda_output.py`

- [ ] **Step 1: Run the focused runtime-node suite**

Run: `pytest tests/unit/test_runtime_nodes.py -k "section_dynamics" -v`

Expected: PASS

- [ ] **Step 2: Run the focused fixture-control suite**

Run: `pytest tests/unit/test_fixture_control.py -v`

Expected: PASS, including the existing laser-program selection tests plus the new mover/panel/laser-dynamics coverage.

- [ ] **Step 3: Run the focused ILDA suite**

Run: `pytest tests/unit/test_ilda_output.py -v`

Expected: PASS, including existing playback-program tests and the new section-dynamics coverage.

- [ ] **Step 4: Run one combined smoke command**

Run: `pytest tests/unit/test_runtime_nodes.py tests/unit/test_fixture_control.py tests/unit/test_ilda_output.py -q`

Expected: all selected tests PASS with no import errors or runtime-context regressions.

- [ ] **Step 5: Commit**

```bash
git commit --allow-empty -m "test: verify live section dynamics wiring"
```
