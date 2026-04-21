from __future__ import annotations

from pathlib import Path

from photonic_synesthesia.core.config import DMXConfig, FixtureConfig, LaserSafetyConfig, MovingHeadSafetyConfig
from photonic_synesthesia.core.state import MusicStructure, PhotonicState, create_initial_state
from photonic_synesthesia.graph.nodes.dmx_output import DMXOutputNode
from photonic_synesthesia.graph.nodes.fixture_control import LaserControlNode, MovingHeadControlNode
from photonic_synesthesia.platform.runtime_context import (
    PlaybackContext,
    clear_shared_playback_context,
    set_shared_playback_context,
)


def _laser_fixture() -> FixtureConfig:
    return FixtureConfig(
        id="laser-main",
        name="Main Laser",
        type="laser",
        profile="laser_generic_7ch",
        start_address=1,
        enabled=True,
    )


def _moving_head_fixture() -> FixtureConfig:
    return FixtureConfig(
        id="mover-main",
        name="Mover Main",
        type="moving_head",
        profile="moving_head_generic",
        start_address=1,
        enabled=True,
    )


def _moving_head_state_with_section(
    *,
    section_overrides: dict[str, object],
    structure: MusicStructure = MusicStructure.DROP,
    beat_phase: float = 0.05,
    bar_position: int = 2,
    bpm: float = 128.0,
    energy: float = 0.72,
    timestamp: float = 1.37,
) -> PhotonicState:
    return _moving_head_state_with_snapshot(
        show_sections=[
            {
                "id": "section_000",
                "start_seconds": 0.0,
                "end_seconds": 8.0,
                **section_overrides,
            }
        ],
        playhead_seconds=1.0,
        structure=structure,
        beat_phase=beat_phase,
        bar_position=bar_position,
        bpm=bpm,
        energy=energy,
        timestamp=timestamp,
    )


def _moving_head_state_with_snapshot(
    *,
    show_sections: list[dict[str, object]],
    playhead_seconds: float,
    structure: MusicStructure = MusicStructure.DROP,
    beat_phase: float = 0.05,
    bar_position: int = 2,
    bpm: float = 128.0,
    energy: float = 0.72,
    timestamp: float = 1.37,
) -> PhotonicState:
    state = create_initial_state()
    state["timestamp"] = timestamp
    state["current_structure"] = structure
    state["beat_info"]["beat_phase"] = beat_phase
    state["beat_info"]["bar_position"] = bar_position
    state["fused_bpm"] = bpm
    state["audio_features"]["rms_energy"] = energy
    state["playback_snapshot"] = {
        "playhead_seconds": playhead_seconds,
        "show_sections": show_sections,
    }
    return state


def test_moving_head_control_uses_active_fill_look_from_laser_program() -> None:
    node = MovingHeadControlNode([_moving_head_fixture()], MovingHeadSafetyConfig())
    playback = set_shared_playback_context(
        PlaybackContext(
            file_path="/tmp/track.mp3",
            file_name="track.mp3",
            duration_seconds=120.0,
            show_sections=[
                {
                    "id": "section_000",
                    "label": "Drop A",
                    "kind": "drop",
                    "start_seconds": 0.0,
                    "end_seconds": 32.0,
                    "intensity_multiplier": 1.0,
                    "motion_multiplier": 1.0,
                    "strobe_level": 1.0,
                    "movers_enabled": True,
                    "laser_program": {
                        "phrase_role": "drop_variation",
                        "zone_policy": "crowd_punctuate",
                        "fill_trigger_every_bars": 4,
                        "launch": {"pattern": "fan", "geometry_family": "fan", "bars": 2},
                        "sustain": [
                            {
                                "pattern": "tunnel",
                                "geometry_family": "tunnel",
                                "color_mode": "dual_cycle",
                                "target_bias": "mid_air",
                                "bars": 8,
                            }
                        ],
                        "fills": [
                            {
                                "pattern": "burst_fan",
                                "geometry_family": "burst",
                                "color_mode": "white_hits",
                                "target_bias": "crowd",
                                "emphasis": 0.9,
                                "motion": 1.3,
                                "bars": 2,
                            }
                        ],
                        "release": {"pattern": "circle_trace", "geometry_family": "trace", "bars": 2},
                    },
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

    state = create_initial_state()
    state["current_structure"] = MusicStructure.DROP
    state["beat_info"]["beat_phase"] = 0.05
    state["beat_info"]["bar_position"] = 3
    state["fused_bpm"] = 128.0
    state["audio_features"]["rms_energy"] = 0.82
    state["director_state"]["subphrase_role"] = "fill"

    try:
        result = node(state)
    finally:
        clear_shared_playback_context()

    command = result["fixture_commands"][0]["channel_values"]
    assert command[1 + node.channel_map["pan_tilt_speed"]] == 218
    assert command[1 + node.channel_map["strobe"]] == 208
    assert command[1 + node.channel_map["gobo"]] == 0
    assert command[1 + node.channel_map["red"]] == 255
    assert command[1 + node.channel_map["green"]] == 255
    assert command[1 + node.channel_map["blue"]] == 255


def test_moving_head_control_uses_release_look_to_relax_motion() -> None:
    node = MovingHeadControlNode([_moving_head_fixture()], MovingHeadSafetyConfig())
    playback = set_shared_playback_context(
        PlaybackContext(
            file_path="/tmp/track.mp3",
            file_name="track.mp3",
            duration_seconds=120.0,
            show_sections=[
                {
                    "id": "section_000",
                    "label": "Breakdown",
                    "kind": "breakdown",
                    "start_seconds": 0.0,
                    "end_seconds": 32.0,
                    "intensity_multiplier": 1.0,
                    "motion_multiplier": 1.0,
                    "strobe_level": 1.0,
                    "movers_enabled": True,
                    "laser_program": {
                        "phrase_role": "breakdown_release",
                        "zone_policy": "overhead_only",
                        "fill_trigger_every_bars": 8,
                        "launch": {"pattern": "fan", "geometry_family": "fan", "bars": 1},
                        "sustain": [
                            {
                                "pattern": "helix",
                                "geometry_family": "helix",
                                "color_mode": "morph",
                                "target_bias": "mid_air",
                                "bars": 7,
                            }
                        ],
                        "fills": [],
                        "release": {
                            "pattern": "square_trace",
                            "geometry_family": "trace",
                            "color_mode": "static",
                            "target_bias": "crowd",
                            "bars": 2,
                        },
                    },
                },
            ],
        )
    )
    playback.update_transport(
        playhead_seconds=30.5,
        playing=True,
        finished=False,
        realtime=True,
        speed=1.0,
    )

    state = create_initial_state()
    state["current_structure"] = MusicStructure.BREAKDOWN
    state["beat_info"]["beat_phase"] = 0.22
    state["beat_info"]["bar_position"] = 4
    state["fused_bpm"] = 122.0
    state["audio_features"]["rms_energy"] = 0.4

    try:
        result = node(state)
    finally:
        clear_shared_playback_context()

    command = result["fixture_commands"][0]["channel_values"]
    assert command[1 + node.channel_map["pan_tilt_speed"]] == 96
    assert command[1 + node.channel_map["strobe"]] == 0
    assert command[1 + node.channel_map["gobo"]] == 64
    # Color is now driven by director_state.color_theme (the test leaves
    # it at the default "neutral" palette) rendered through color_mode
    # "static" — so we expect the neutral palette's primary tinted toward
    # the accent by color_drive * 0.15 (see director.palettes.render_rgb).
    # No more hardcoded target-bias red-orange / ceiling-blue fall-through.
    red = command[1 + node.channel_map["red"]]
    green = command[1 + node.channel_map["green"]]
    blue = command[1 + node.channel_map["blue"]]
    assert 0 <= red <= 255 and 0 <= green <= 255 and 0 <= blue <= 255
    # Neutral palette biases R~=G~=B; blue is slightly higher than red.
    assert blue >= red and blue >= green - 10


def test_movers_enabled_flag_clears_moving_head_dmx_output() -> None:
    mover_node = MovingHeadControlNode([_moving_head_fixture()], MovingHeadSafetyConfig())
    dmx_output = DMXOutputNode(DMXConfig(interface_type="artnet"))

    active_state = _moving_head_state_with_section(
        section_overrides={"movers_enabled": True},
        beat_phase=0.05,
        timestamp=1.37,
    )
    active_state["control_state"]["armed_live"] = True

    disabled_state = _moving_head_state_with_section(
        section_overrides={"movers_enabled": False},
        beat_phase=0.05,
        timestamp=1.37,
    )
    disabled_state["control_state"]["armed_live"] = True

    active_result = dmx_output(mover_node(active_state))
    disabled_result = dmx_output(mover_node(disabled_state))

    active_universe = active_result["dmx_universe"]
    disabled_universe = disabled_result["dmx_universe"]

    assert any(active_universe[channel] > 0 for channel in range(1, 17))
    assert all(disabled_universe[channel] == 0 for channel in range(1, 17))


def test_gap_playhead_does_not_borrow_last_section_mover_program_look() -> None:
    node = MovingHeadControlNode([_moving_head_fixture()], MovingHeadSafetyConfig())

    result = node(
        _moving_head_state_with_snapshot(
            show_sections=[
                {
                    "id": "section_intro",
                    "start_seconds": 0.0,
                    "end_seconds": 1.0,
                    "movers_enabled": True,
                },
                {
                    "id": "section_future",
                    "start_seconds": 3.0,
                    "end_seconds": 5.0,
                    "movers_enabled": True,
                    "laser_program": {
                        "phrase_role": "breakdown_release",
                        "release": {
                            "pattern": "square_trace",
                            "geometry_family": "trace",
                            "color_mode": "static",
                            "target_bias": "crowd",
                            "bars": 2,
                        },
                    },
                },
            ],
            playhead_seconds=2.0,
            structure=MusicStructure.DROP,
            beat_phase=0.05,
            timestamp=1.37,
        )
    )

    command = result["fixture_commands"][0]["channel_values"]
    assert command[1 + node.channel_map["pan_tilt_speed"]] == 218
    assert command[1 + node.channel_map["strobe"]] == 208
    assert command[1 + node.channel_map["gobo"]] == 0


def test_motion_intensity_and_strobe_from_section_dynamics() -> None:
    node = MovingHeadControlNode([_moving_head_fixture()], MovingHeadSafetyConfig())

    reduced = node(
        _moving_head_state_with_section(
            section_overrides={
                "movers_enabled": True,
                "intensity_multiplier": 0.45,
                "motion_multiplier": 0.55,
                "strobe_level": 0.0,
            },
            beat_phase=0.05,
            timestamp=1.37,
        )
    )["fixture_commands"][0]["channel_values"]
    boosted = node(
        _moving_head_state_with_section(
            section_overrides={
                "movers_enabled": True,
                "intensity_multiplier": 1.25,
                "motion_multiplier": 1.6,
                "strobe_level": 0.85,
            },
            beat_phase=0.05,
            timestamp=1.37,
        )
    )["fixture_commands"][0]["channel_values"]

    assert boosted[1 + node.channel_map["pan_tilt_speed"]] > reduced[1 + node.channel_map["pan_tilt_speed"]]
    assert boosted[1 + node.channel_map["pan"]] != reduced[1 + node.channel_map["pan"]]
    assert boosted[1 + node.channel_map["dimmer"]] > reduced[1 + node.channel_map["dimmer"]]
    assert reduced[1 + node.channel_map["strobe"]] == 0
    assert boosted[1 + node.channel_map["strobe"]] > 0


def test_laser_control_clears_dmx_universe_when_active_section_disables_lasers() -> None:
    laser_node = LaserControlNode([_laser_fixture()], LaserSafetyConfig(y_axis_max=96), fixtures_dir=Path("config/fixtures"))
    dmx_output = DMXOutputNode(DMXConfig(interface_type="artnet"))
    playback = set_shared_playback_context(
        PlaybackContext(
            file_path="/tmp/track.mp3",
            file_name="track.mp3",
            duration_seconds=12.0,
            show_sections=[
                {
                    "id": "section_enabled",
                    "start_seconds": 0.0,
                    "end_seconds": 5.0,
                    "laser_enabled": True,
                },
                {
                    "id": "section_disabled",
                    "start_seconds": 5.0,
                    "end_seconds": 12.0,
                    "laser_enabled": False,
                }
            ],
        )
    )
    playback.update_transport(
        playhead_seconds=2.0,
        playing=True,
        finished=False,
        realtime=True,
        speed=1.0,
    )

    active_state = create_initial_state()
    active_state["timestamp"] = 1.0
    active_state["current_structure"] = MusicStructure.DROP
    active_state["beat_info"]["beat_phase"] = 0.125
    active_state["fused_bpm"] = 128.0
    active_state["audio_features"]["rms_energy"] = 0.75
    active_state["control_state"]["armed_live"] = True

    try:
        active_result = dmx_output(laser_node(active_state))

        playback.update_transport(
            playhead_seconds=7.0,
            playing=True,
            finished=False,
            realtime=True,
            speed=1.0,
        )

        disabled_state = create_initial_state()
        disabled_state["timestamp"] = 2.0
        disabled_state["current_structure"] = MusicStructure.DROP
        disabled_state["beat_info"]["beat_phase"] = 0.125
        disabled_state["fused_bpm"] = 128.0
        disabled_state["audio_features"]["rms_energy"] = 0.75
        disabled_state["control_state"]["armed_live"] = True
        disabled_result = dmx_output(laser_node(disabled_state))
    finally:
        clear_shared_playback_context()

    active_universe = active_result["dmx_universe"]
    disabled_universe = disabled_result["dmx_universe"]

    assert active_universe[1] == 200
    assert any(active_universe[channel] > 0 for channel in range(1, 8))
    assert all(disabled_universe[channel] == 0 for channel in range(1, 8))
