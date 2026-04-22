"""Task 3 acceptance: TriggerRouterNode + PrepositionNode + SurfaceCompositorNode + LaserZoneRuntimeNode.

Pins the cycle-N invariants in the new nodes:
- TriggerRouter first-tick fires `at_seconds=0.0` flags (cycle-3 3C-N1).
- TriggerRouter doesn't re-fire on transport-revision-only ticks (cycle-1 UF-9).
- TriggerRouter pre-populates past flags on a mid-show authored change so
  flags don't thunder-herd (cycle-3 3C-N1 / cycle-2 NC-4).
- Preposition emits per-fixture targets (cycle-1 UF-21).
- SurfaceCompositor expands group-label targets (cycle-2 NC-9).
- LaserZoneRuntime clamps brightness to [0, 255] with unbiased rounding
  (cycle-1 UF-19/UF-35).
- LaserZoneRuntime applies per-fixture protected half-plane (cycle-1 UF-20).
"""

from __future__ import annotations

from photonic_synesthesia.core.state import create_initial_state
from photonic_synesthesia.core.config import FixtureConfig
from photonic_synesthesia.graph.nodes.section_dynamics import (
    _bool_or_default,
    resolve_laser_pattern_override,
    resolve_mover_pattern_family,
    resolve_panel_render_mode,
    resolve_active_section_dynamics,
)
from photonic_synesthesia.graph.nodes.laser_zone_runtime import (
    LaserZoneRuntimeNode,
    _channel_clamp,
)
from photonic_synesthesia.graph.nodes.preposition import PrepositionNode
from photonic_synesthesia.graph.nodes.surface_compositor import SurfaceCompositorNode
from photonic_synesthesia.graph.nodes.trigger_router import TriggerRouterNode
from photonic_synesthesia.platform.runtime_context import (
    PlaybackContext,
    clear_shared_playback_context,
    set_shared_playback_context,
)


# --- TriggerRouterNode -----------------------------------------------------

def _flag(id_: str, at: float, kind: str = "phrase_head") -> dict:
    return {"id": id_, "kind": kind, "at_seconds": at, "payload": {"section_id": id_.split(":")[0]}}


# --- SectionDynamics -------------------------------------------------------


def test_resolve_active_section_dynamics_defaults_without_snapshot() -> None:
    clear_shared_playback_context()
    dynamics = resolve_active_section_dynamics(create_initial_state())

    assert dynamics["section_id"] is None
    assert dynamics["current_section"] is None
    assert dynamics["intensity_multiplier"] == 1.0
    assert dynamics["motion_multiplier"] == 1.0
    assert dynamics["strobe_level"] == 0.0
    assert dynamics["laser_enabled"] is True
    assert dynamics["movers_enabled"] is True
    assert dynamics["washes_enabled"] is True
    assert dynamics["leds_enabled"] is True
    assert dynamics["panel_family"] is None


def test_resolve_active_section_dynamics_treats_empty_state_snapshot_as_explicit_local_state() -> None:
    state = create_initial_state()
    state["playback_snapshot"] = {}
    playback = set_shared_playback_context(
        PlaybackContext(
            file_path="/tmp/track.mp3",
            file_name="track.mp3",
            duration_seconds=120.0,
            show_sections=[
                {
                    "id": "shared-sec-1",
                    "start_seconds": 0.0,
                    "end_seconds": 8.0,
                    "intensity_multiplier": 0.6,
                }
            ],
        )
    )
    playback.update_transport(
        playhead_seconds=4.0,
        playing=True,
        finished=False,
        realtime=True,
        speed=1.0,
    )

    try:
        dynamics = resolve_active_section_dynamics(state)
    finally:
        clear_shared_playback_context()

    assert dynamics["section_id"] is None
    assert dynamics["current_section"] is None
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
    state.pop("playback_snapshot", None)
    playback = set_shared_playback_context(
        PlaybackContext(
            file_path="/tmp/track.mp3",
            file_name="track.mp3",
            duration_seconds=120.0,
            show_sections=[
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
        )
    )
    playback.update_transport(
        playhead_seconds=14.0,
        playing=True,
        finished=False,
        realtime=True,
        speed=1.0,
    )

    try:
        dynamics = resolve_active_section_dynamics(state)
    finally:
        clear_shared_playback_context()

    assert dynamics["section_id"] == "sec-2"
    assert dynamics["current_section"] == playback.snapshot()["show_sections"][1]
    assert dynamics["intensity_multiplier"] == 0.75
    assert dynamics["motion_multiplier"] == 1.3
    assert dynamics["strobe_level"] == 0.4
    assert dynamics["laser_enabled"] is False
    assert dynamics["movers_enabled"] is True
    assert dynamics["washes_enabled"] is False
    assert dynamics["leds_enabled"] is True
    assert dynamics["panel_family"] == "wash"


def test_resolve_active_section_dynamics_returns_defaults_when_playhead_is_before_first_section_or_in_gap() -> None:
    for playhead_seconds in (-1.0, 9.0):
        state = create_initial_state()
        state["playback_snapshot"] = {
            "playhead_seconds": playhead_seconds,
            "show_sections": [
                {
                    "id": "sec-1",
                    "start_seconds": 0.0,
                    "end_seconds": 8.0,
                    "intensity_multiplier": 0.6,
                    "motion_multiplier": 0.8,
                    "strobe_level": 0.2,
                    "laser_enabled": False,
                },
                {
                    "id": "sec-2",
                    "start_seconds": 10.0,
                    "end_seconds": 20.0,
                    "intensity_multiplier": 0.75,
                    "motion_multiplier": 1.3,
                    "strobe_level": 0.4,
                    "laser_enabled": False,
                    "movers_enabled": False,
                    "washes_enabled": False,
                    "leds_enabled": False,
                },
            ],
        }

        dynamics = resolve_active_section_dynamics(state)

        assert dynamics["section_id"] is None
        assert dynamics["current_section"] is None
        assert dynamics["intensity_multiplier"] == 1.0
        assert dynamics["motion_multiplier"] == 1.0
        assert dynamics["strobe_level"] == 0.0
        assert dynamics["laser_enabled"] is True
        assert dynamics["movers_enabled"] is True
        assert dynamics["washes_enabled"] is True
        assert dynamics["leds_enabled"] is True
        assert dynamics["panel_family"] is None


def test_section_dynamics_bool_or_default_falls_back_to_default_for_unrecognized_strings() -> None:
    assert _bool_or_default("off", True) is False
    assert _bool_or_default("on", False) is True
    assert _bool_or_default("disabled", False) is False
    assert _bool_or_default("maybe", True) is True


def test_section_dynamics_bool_or_default_falls_back_to_default_for_malformed_non_string_values() -> None:
    assert _bool_or_default({}, True) is True
    assert _bool_or_default([], False) is False
    assert _bool_or_default(("unexpected",), True) is True
    assert _bool_or_default(object(), False) is False


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
    assert dynamics["current_section"] == state["playback_snapshot"]["show_sections"][0]
    assert dynamics["intensity_multiplier"] == 1.0
    assert dynamics["motion_multiplier"] == 1.0
    assert dynamics["strobe_level"] == 0.0
    assert dynamics["laser_enabled"] is False
    assert dynamics["movers_enabled"] is True
    assert dynamics["washes_enabled"] is True
    assert dynamics["leds_enabled"] is True
    assert dynamics["panel_family"] == "led"


def test_resolve_active_section_dynamics_requires_dict_fixture_role_entries_for_panel_family() -> None:
    state = create_initial_state()
    state["playback_snapshot"] = {
        "playhead_seconds": 4.0,
        "show_sections": [
            {
                "id": "sec-1",
                "start_seconds": 0.0,
                "end_seconds": 10.0,
                "laser_enabled": "disabled",
                "movers_enabled": "maybe",
                "washes_enabled": "off",
                "leds_enabled": "on",
                "fixture_role_map": {"led": ["support"]},
            }
        ],
    }

    dynamics = resolve_active_section_dynamics(state)

    assert dynamics["section_id"] == "sec-1"
    assert dynamics["laser_enabled"] is True
    assert dynamics["movers_enabled"] is True
    assert dynamics["washes_enabled"] is False
    assert dynamics["leds_enabled"] is True
    assert dynamics["panel_family"] is None


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
    pan_sweep_family = resolve_mover_pattern_family("pan_sweep")
    wash_render = resolve_panel_render_mode("bloom", "wash")
    led_render = resolve_panel_render_mode("chase", "led")
    wash_fallback = resolve_panel_render_mode("bloom", None)
    shared_fallback = resolve_panel_render_mode("fade", None)

    assert dmx_pattern is not None
    assert geometry_family == "burst"
    assert mover_family == "hold"
    assert pan_sweep_family == "cross"
    assert wash_render == "bloom"
    assert led_render == "chase"
    assert wash_fallback == "bloom"
    assert shared_fallback == "fade"


def test_trigger_router_fires_zero_at_seconds_flag_on_first_tick() -> None:
    """Cycle-3 panel 3C-N1: first tick MUST NOT pre-populate; canonical
    section-0 phrase_head flag at at_seconds=0.0 fires normally."""
    node = TriggerRouterNode()
    state = {
        "playback_snapshot": {
            "playhead_seconds": 0.0,
            "timeline_flag_revision": 0,
            "timeline_flags": [_flag("sec-0:phrase_head", 0.0)],
        },
        "trigger_events": [],
    }
    result = node(state)
    fired = [e["id"] for e in result["trigger_events"]]
    assert "sec-0:phrase_head" in fired, "first tick must fire at_seconds=0.0 flags"


def test_trigger_router_does_not_refire_on_transport_only_ticks() -> None:
    """Cycle-1 panel UF-9: ledger keys on timeline_flag_revision, not
    transport_revision. Repeated calls with same authored state and
    forward playhead must NOT re-fire."""
    node = TriggerRouterNode()
    base_snap = {
        "playhead_seconds": 32.0,
        "timeline_flag_revision": 4,
        "timeline_flags": [_flag("sec-1:handoff", 31.5, "handoff")],
    }
    first = node({"playback_snapshot": dict(base_snap), "trigger_events": []})
    second = node({"playback_snapshot": dict(base_snap), "trigger_events": []})
    assert first["trigger_events"] == [
        {"id": "sec-1:handoff", "kind": "handoff", "payload": {"section_id": "sec-1"}}
    ]
    assert second["trigger_events"] == []


def test_trigger_router_pre_populates_past_flags_on_mid_show_authored_change() -> None:
    """Cycle-2 panel NC-4 / cycle-3 panel 3C-N1: when authored state changes
    at a non-zero playhead (revision_changed=True, rewound=False, NOT first
    tick), past flags are pre-populated as already-seen so only newly-crossed
    flags fire — no thundering herd."""
    node = TriggerRouterNode()
    # First tick at playhead 10s, authored state revision 1, two flags
    # both already past (0s, 5s) — both fire on first tick (correct).
    state1 = {
        "playback_snapshot": {
            "playhead_seconds": 10.0,
            "timeline_flag_revision": 1,
            "timeline_flags": [_flag("a:phrase_head", 0.0), _flag("b:phrase_head", 5.0)],
        },
        "trigger_events": [],
    }
    result1 = node(state1)
    assert {e["id"] for e in result1["trigger_events"]} == {"a:phrase_head", "b:phrase_head"}

    # Operator commits a new look at playhead 10s — authored revision bumps.
    # Flags unchanged but revision changed. Past flags must NOT re-fire.
    state2 = {
        "playback_snapshot": {
            "playhead_seconds": 10.0,
            "timeline_flag_revision": 2,  # bumped
            "timeline_flags": [_flag("a:phrase_head", 0.0), _flag("b:phrase_head", 5.0)],
        },
        "trigger_events": [],
    }
    result2 = node(state2)
    assert result2["trigger_events"] == [], "past flags must not thunder-herd on revision bump"


def test_trigger_router_rewind_clears_ledger_for_replay() -> None:
    """Cycle-3 panel 3C-N1: rewind (backward seek) clears the ledger so
    past flags re-fire on the replay."""
    node = TriggerRouterNode()
    # Forward to 10s, fire a 0s flag.
    node({
        "playback_snapshot": {
            "playhead_seconds": 10.0,
            "timeline_flag_revision": 1,
            "timeline_flags": [_flag("a:phrase_head", 0.0)],
        },
        "trigger_events": [],
    })
    # Rewind to 0s, same revision — flag should re-fire.
    result = node({
        "playback_snapshot": {
            "playhead_seconds": 0.0,
            "timeline_flag_revision": 1,
            "timeline_flags": [_flag("a:phrase_head", 0.0)],
        },
        "trigger_events": [],
    })
    assert "a:phrase_head" in {e["id"] for e in result["trigger_events"]}


# --- PrepositionNode -------------------------------------------------------

def _moving_head(id_: str = "mh-1") -> FixtureConfig:
    return FixtureConfig(
        id=id_, name="Test Mover", type="moving_head",
        profile="generic_moving_head", start_address=1, enabled=True,
    )


def test_preposition_emits_per_fixture_targets_in_release_window() -> None:
    """Cycle-1 panel UF-21: each target carries fixture_id."""
    node = PrepositionNode(fixtures=[_moving_head("mh-1"), _moving_head("mh-2")])
    state = {
        "playback_snapshot": {
            "playhead_seconds": 8.0,
            "show_sections": [{
                "id": "sec-1", "start_seconds": 0.0, "end_seconds": 32.0,
                "preposition_intent": {"enabled": True, "when": "release", "targets": ["fan_open"]},
            }],
        },
        "control_state": {"blackout_active": False},
        "director_state": {"subphrase_role": "release"},
    }
    result = node(state)
    targets = result["preposition_targets"]
    assert {t["fixture_id"] for t in targets} == {"mh-1", "mh-2"}
    assert all(t["preset"] == "fan_open" for t in targets)


def test_preposition_emits_nothing_outside_release_window() -> None:
    node = PrepositionNode(fixtures=[_moving_head()])
    state = {
        "playback_snapshot": {
            "playhead_seconds": 8.0,
            "show_sections": [{
                "id": "sec-1", "start_seconds": 0.0, "end_seconds": 32.0,
                "preposition_intent": {"enabled": True, "when": "release", "targets": ["fan_open"]},
            }],
        },
        "control_state": {"blackout_active": False},
        "director_state": {"subphrase_role": "drive"},  # not release/settle
    }
    assert node(state)["preposition_targets"] == []


# --- SurfaceCompositorNode -------------------------------------------------

def _panel(id_: str, surface_group: str | None = None) -> FixtureConfig:
    return FixtureConfig(
        id=id_, name=f"Panel {id_}", type="panel",
        profile="generic_panel", start_address=1, enabled=True,
        surface_group=surface_group,
    )


def test_surface_compositor_routes_exact_id_target_to_one_fixture() -> None:
    node = SurfaceCompositorNode(fixtures=[_panel("panel-1"), _panel("panel-2")])
    state = {
        "playback_snapshot": {
            "playhead_seconds": 10.0,
            "show_sections": [{
                "id": "sec-1", "start_seconds": 0.0, "end_seconds": 30.0,
                "surface_program": {"surface_mode": "texture", "target": "panel-1"},
            }],
        },
    }
    layers = node(state)["surface_layers"]
    assert len(layers) == 1
    assert layers[0]["fixture_id"] == "panel-1"
    assert layers[0]["surface_mode"] == "texture"


def test_surface_compositor_expands_group_target_to_all_panels_in_group() -> None:
    """Cycle-2 panel NC-9: group-label target expands to per-fixture layers."""
    node = SurfaceCompositorNode(fixtures=[
        _panel("panel-1", surface_group="led_wall"),
        _panel("panel-2", surface_group="led_wall"),
        _panel("panel-3", surface_group="floor"),
    ])
    state = {
        "playback_snapshot": {
            "playhead_seconds": 5.0,
            "show_sections": [{
                "id": "sec-1", "start_seconds": 0.0, "end_seconds": 30.0,
                "surface_program": {"surface_mode": "accent", "target": "led_wall"},
            }],
        },
    }
    layers = node(state)["surface_layers"]
    assert {layer["fixture_id"] for layer in layers} == {"panel-1", "panel-2"}, \
        "group target should fan out to every matching panel"


# --- LaserZoneRuntimeNode --------------------------------------------------

def test_channel_clamp_clamps_to_dmx_range_with_unbiased_rounding() -> None:
    """Cycle-1 panel UF-19 + UF-35."""
    assert _channel_clamp(-50) == 0  # negative → floor
    assert _channel_clamp(0) == 0
    assert _channel_clamp(127.5) == 128  # banker's rounding
    assert _channel_clamp(255) == 255
    assert _channel_clamp(500) == 255  # over-range → ceiling
    assert _channel_clamp(float("nan")) == 0


def _laser(id_: str = "laser-1") -> FixtureConfig:
    return FixtureConfig(
        id=id_, name="Laser", type="laser",
        profile="generic_laser", start_address=1, enabled=True,
    )


def test_laser_zone_runtime_clamps_brightness_and_blanks_protected_half_plane() -> None:
    """Cycle-1 panel UF-19 + UF-20: brightness clamped, default y<0 blanked
    when protected=True."""
    node = LaserZoneRuntimeNode(fixtures=[_laser()])
    state = {
        "laser_zone_rules": {
            "laser-1": {"brightness_cap": 1.5, "protected": True, "policy": "overhead_only"},
        },
        "ilda_frames": [{
            "fixture_id": "laser-1",
            "points": [
                {"x": 0.0, "y": 0.2, "r": 100, "g": 100, "b": 100, "blanked": False},
                {"x": 0.0, "y": -0.2, "r": 255, "g": 255, "b": 255, "blanked": False},
            ],
        }],
    }
    points = node(state)["ilda_frames"][0]["points"]
    # Point 0 (y > 0): kept, brightness clamped (100 * 1.5 = 150).
    assert points[0]["blanked"] is False
    assert points[0]["r"] == 150
    # Point 1 (y < 0, protected, default below-is-protected=True): blanked.
    # Brightness clamped at 255 ceiling (255 * 1.5 = 382.5 → 255).
    assert points[1]["blanked"] is True
    assert points[1]["r"] == 255


def test_laser_zone_runtime_passes_through_when_no_rule_for_fixture() -> None:
    """Frames for fixtures without a zone rule pass through unmodified."""
    node = LaserZoneRuntimeNode(fixtures=[_laser()])
    state = {
        "laser_zone_rules": {},
        "ilda_frames": [{
            "fixture_id": "laser-1",
            "points": [{"x": 0.0, "y": 0.5, "r": 200, "g": 0, "b": 0, "blanked": False}],
        }],
    }
    points = node(state)["ilda_frames"][0]["points"]
    # Default cap 1.0 applied; 200 * 1.0 = 200, no blank.
    assert points[0]["r"] == 200
    assert points[0]["blanked"] is False
