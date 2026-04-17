from __future__ import annotations

from photonic_synesthesia.core.config import FixtureConfig, MovingHeadSafetyConfig
from photonic_synesthesia.core.state import MusicStructure, create_initial_state
from photonic_synesthesia.graph.nodes.fixture_control import MovingHeadControlNode
from photonic_synesthesia.platform.runtime_context import (
    PlaybackContext,
    clear_shared_playback_context,
    set_shared_playback_context,
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
                }
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
                }
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
    assert command[1 + node.channel_map["red"]] == 70
    assert command[1 + node.channel_map["green"]] == 130
    assert command[1 + node.channel_map["blue"]] == 255
