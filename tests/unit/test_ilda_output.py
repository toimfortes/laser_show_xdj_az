from __future__ import annotations

import copy
from pathlib import Path
from unittest.mock import MagicMock, patch

from photonic_synesthesia.core.config import FixtureConfig, ILDAConfig, LaserSafetyConfig
from photonic_synesthesia.core.state import (
    ILDAFrame,
    ILDAPoint,
    MusicStructure,
    create_initial_state,
)
from photonic_synesthesia.graph.nodes.ilda_output import ILDADACOutputNode, ILDAOutputNode
from photonic_synesthesia.graph.nodes.laser_vector_interlock import LaserVectorInterlockNode
from photonic_synesthesia.laser.ilda_file import encode_ild
from photonic_synesthesia.platform.runtime_context import (
    PlaybackContext,
    clear_shared_playback_context,
    set_shared_playback_context,
)


def _armed_state():
    state = create_initial_state()
    state["control_state"]["armed_live"] = True
    return state


def _ilda_state_with_frames(frames: list[ILDAFrame]):
    state = _armed_state()
    state["ilda_frames"] = frames
    return state


def _ilda_state_with_section(
    *,
    show_sections: list[dict[str, object]],
    playhead_seconds: float,
    structure: MusicStructure = MusicStructure.DROP,
    beat_phase: float = 0.05,
    bar_position: int = 2,
    bpm: float = 128.0,
) -> dict[str, object]:
    state = _armed_state()
    state["current_structure"] = structure
    state["fused_bpm"] = bpm
    state["beat_info"]["beat_phase"] = beat_phase
    state["beat_info"]["bar_position"] = bar_position
    state["playback_snapshot"] = {
        "playhead_seconds": playhead_seconds,
        "show_sections": show_sections,
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


def _ilda_state_for_single_section(
    *,
    section_overrides: dict[str, object],
    structure: MusicStructure = MusicStructure.DROP,
    beat_phase: float = 0.05,
    bar_position: int = 2,
    bpm: float = 128.0,
    timestamp: float = 1.0,
) -> dict[str, object]:
    state = _ilda_state_with_section(
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
    )
    state["timestamp"] = timestamp
    state["director_state"]["laser_aggression"] = 0.9
    state["director_state"]["laser_motion_energy"] = 0.8
    state["director_state"]["color_drive"] = 0.7
    state["audio_features"]["harmonic_change"] = 0.41
    state["audio_features"]["pitch_height"] = 0.58
    state["audio_features"]["timbral_harshness"] = 0.42
    return state


def _synthetic_ilda_frame(
    fixture_id: str = "laser-main",
    point_count: int = 24,
    profile_name: str = "laser_aucd_cx338b_hybrid",
) -> ILDAFrame:
    points = [
        ILDAPoint(x=0, y=0, r=255, g=128, b=64, blanked=False)
        for _ in range(point_count)
    ]
    return ILDAFrame(
        fixture_id=fixture_id,
        profile_name=profile_name,
        geometry_family="burst",
        color_mode="morph",
        target_bias="crowd",
        point_count=point_count,
        repeat=True,
        points=points,
    )


def test_ilda_output_generates_frame_for_hybrid_laser() -> None:
    fixture = FixtureConfig(
        id="laser-main",
        name="Main Laser",
        type="laser",
        profile="laser_aucd_cx338b_hybrid",
        start_address=1,
        enabled=True,
    )
    node = ILDAOutputNode(
        ILDAConfig(enabled=True, points_per_frame=48),
        [fixture],
        LaserSafetyConfig(y_axis_max=96),
        fixtures_dir=Path("config/fixtures"),
    )
    state = _armed_state()
    state["current_structure"] = MusicStructure.DROP
    state["fused_bpm"] = 126.0
    state["beat_info"]["beat_phase"] = 0.08
    state["audio_features"]["harmonic_change"] = 0.41
    state["audio_features"]["pitch_height"] = 0.58
    state["audio_features"]["timbral_harshness"] = 0.82
    state["director_state"]["laser_aggression"] = 0.84
    state["director_state"]["melodic_smoothness"] = 0.29
    state["director_state"]["color_drive"] = 0.63

    result = node(state)

    assert len(result["ilda_frames"]) == 1
    frame = result["ilda_frames"][0]
    assert frame["fixture_id"] == "laser-main"
    assert frame["geometry_family"] == "burst"
    assert frame["color_mode"] == "white_hits"
    assert frame["target_bias"] == "crowd"
    assert frame["point_count"] == 48
    assert len(frame["points"]) == 48
    assert any(point["blanked"] for point in frame["points"])
    assert all(-32767 <= point["x"] <= 32767 for point in frame["points"])
    assert all(-32767 <= point["y"] <= 32767 for point in frame["points"])
    y_cap = int((96 / 255.0) * 32767)
    assert all(point["y"] <= y_cap for point in frame["points"])


def test_ilda_output_uses_active_laser_program_when_playback_context_exists() -> None:
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
            duration_seconds=120.0,
            show_sections=[
                {
                    "id": "section_000",
                    "label": "Drop A",
                    "kind": "drop",
                    "start_seconds": 0.0,
                    "end_seconds": 64.0,
                    "laser_program": {
                        "phrase_role": "drop_variation",
                        "zone_policy": "overhead_only",
                        "fill_trigger_every_bars": 4,
                        "launch": {
                            "pattern": "sheet",
                            "geometry_family": "sheet",
                            "color_mode": "dual_cycle",
                            "target_bias": "crowd",
                            "bars": 4,
                        },
                        "sustain": [
                            {
                                "pattern": "sequence",
                                "geometry_family": "sequence",
                                "color_mode": "morph",
                                "target_bias": "crowd",
                                "bars": 2,
                            },
                            {
                                "pattern": "helix",
                                "geometry_family": "helix",
                                "color_mode": "dual_cycle",
                                "target_bias": "mid_air",
                                "bars": 6,
                            }
                        ],
                        "fills": [],
                        "release": {
                            "pattern": "circle_trace",
                            "geometry_family": "trace",
                            "color_mode": "morph",
                            "target_bias": "mid_air",
                            "bars": 2,
                        },
                    },
                }
            ],
        )
    )
    playback.update_transport(
        playhead_seconds=40.0,
        playing=True,
        finished=False,
        realtime=True,
        speed=1.0,
    )

    state = _armed_state()
    state["current_structure"] = MusicStructure.DROP
    state["beat_info"]["downbeat"] = False
    state["beat_info"]["bar_position"] = 2
    state["playback_snapshot"] = playback.snapshot()

    try:
        result = node(state)
    finally:
        clear_shared_playback_context()

    frame = result["ilda_frames"][0]
    assert frame["geometry_family"] == "helix"
    assert frame["color_mode"] == "dual_cycle"
    assert frame["target_bias"] == "ceiling"


def test_ilda_output_uses_section_laser_pattern_geometry_override() -> None:
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
    state = _ilda_state_with_section(
        show_sections=[
            {
                "id": "section_000",
                "start_seconds": 0.0,
                "end_seconds": 64.0,
                "laser_enabled": True,
                "laser_pattern": "wave",
                "laser_program": {
                    "phrase_role": "drop_variation",
                    "zone_policy": "overhead_only",
                    "fill_trigger_every_bars": 4,
                    "launch": {
                        "pattern": "sheet",
                        "geometry_family": "sheet",
                        "color_mode": "dual_cycle",
                        "target_bias": "crowd",
                        "bars": 4,
                    },
                    "sustain": [
                        {
                            "pattern": "sequence",
                            "geometry_family": "sequence",
                            "color_mode": "morph",
                            "target_bias": "crowd",
                            "bars": 2,
                        },
                        {
                            "pattern": "helix",
                            "geometry_family": "helix",
                            "color_mode": "dual_cycle",
                            "target_bias": "mid_air",
                            "bars": 6,
                        },
                    ],
                    "fills": [],
                    "release": {
                        "pattern": "circle_trace",
                        "geometry_family": "trace",
                        "color_mode": "morph",
                        "target_bias": "mid_air",
                        "bars": 2,
                    },
                },
            }
        ],
        playhead_seconds=40.0,
        structure=MusicStructure.DROP,
        beat_phase=0.05,
        bar_position=2,
    )

    frame = node(state)["ilda_frames"][0]

    assert frame["geometry_family"] == "scan"
    assert frame["color_mode"] == "dual_cycle"
    assert frame["target_bias"] == "ceiling"


def test_ilda_fixture_mode_intro_reduces_motion_posture_relative_to_peak_return() -> None:
    node = _ilda_node()

    peak_result = node(
        _ilda_state_for_single_section(
            section_overrides={
                "fixture_mode": "peak_return",
                "laser_enabled": True,
            }
        )
    )
    intro_result = node(
        _ilda_state_for_single_section(
            section_overrides={
                "fixture_mode": "intro",
                "laser_enabled": True,
            }
        )
    )

    peak_frame = peak_result["ilda_frames"][0]
    intro_frame = intro_result["ilda_frames"][0]
    peak_span = max(point["x"] for point in peak_frame["points"]) - min(point["x"] for point in peak_frame["points"])
    intro_span = max(point["x"] for point in intro_frame["points"]) - min(point["x"] for point in intro_frame["points"])

    assert peak_span > intro_span


def test_ilda_output_honors_fill_bar_windows_in_laser_program() -> None:
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
                        "zone_policy": "overhead_bias",
                        "fill_trigger_every_bars": 4,
                        "launch": {"pattern": "fan", "geometry_family": "fan", "bars": 2},
                        "sustain": [
                            {"pattern": "tunnel", "geometry_family": "tunnel", "bars": 8},
                        ],
                        "fills": [
                            {"pattern": "sheet", "geometry_family": "sheet", "bars": 2},
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

    state = _armed_state()
    state["current_structure"] = MusicStructure.DROP
    state["director_state"]["subphrase_role"] = "fill"
    state["playback_snapshot"] = playback.snapshot()

    try:
        result = node(state)
    finally:
        clear_shared_playback_context()

    assert result["ilda_frames"][0]["geometry_family"] == "sheet"


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
    base_section = {
        "id": "section_000",
        "start_seconds": 0.0,
        "end_seconds": 32.0,
        "laser_enabled": True,
        "laser_program": {
            "phrase_role": "drop_variation",
            "zone_policy": "overhead_only",
            "fill_trigger_every_bars": 4,
            "launch": {"pattern": "sheet", "geometry_family": "sheet", "bars": 2},
            "sustain": [
                {
                    "pattern": "burst",
                    "geometry_family": "burst",
                    "color_mode": "white_hits",
                    "bars": 8,
                }
            ],
            "fills": [],
            "release": {"pattern": "trace", "geometry_family": "trace", "bars": 2},
        },
    }

    def render_frame(
        *,
        intensity_multiplier: float,
        motion_multiplier: float,
        strobe_level: float,
        timestamp: float,
    ) -> ILDAFrame:
        playback = set_shared_playback_context(
            PlaybackContext(
                file_path="/tmp/track.mp3",
                file_name="track.mp3",
                duration_seconds=32.0,
                show_sections=[
                    {
                        **base_section,
                        "intensity_multiplier": intensity_multiplier,
                        "motion_multiplier": motion_multiplier,
                        "strobe_level": strobe_level,
                    }
                ],
            )
        )
        playback.update_transport(
            playhead_seconds=10.0,
            playing=True,
            finished=False,
            realtime=True,
            speed=1.0,
        )

        state = _armed_state()
        state["timestamp"] = timestamp
        state["current_structure"] = MusicStructure.DROP
        state["fused_bpm"] = 128.0
        state["beat_info"]["beat_phase"] = 0.05
        state["audio_features"]["timbral_harshness"] = 0.85
        state["director_state"]["laser_aggression"] = 0.9
        state["director_state"]["laser_motion_energy"] = 0.8
        state["director_state"]["color_drive"] = 0.7
        state["playback_snapshot"] = playback.snapshot()

        try:
            return copy.deepcopy(node(state)["ilda_frames"][0])
        finally:
            clear_shared_playback_context()

    baseline = render_frame(
        intensity_multiplier=1.0,
        motion_multiplier=1.0,
        strobe_level=1.0,
        timestamp=10.0,
    )
    baseline_next = render_frame(
        intensity_multiplier=1.0,
        motion_multiplier=1.0,
        strobe_level=1.0,
        timestamp=10.05,
    )
    frame = render_frame(
        intensity_multiplier=0.35,
        motion_multiplier=1.6,
        strobe_level=0.0,
        timestamp=10.0,
    )
    frame_next = render_frame(
        intensity_multiplier=0.35,
        motion_multiplier=1.6,
        strobe_level=0.0,
        timestamp=10.05,
    )

    lit_points = [point for point in frame["points"] if not point["blanked"]]
    baseline_lit_points = [point for point in baseline["points"] if not point["blanked"]]
    blanked_points = [point for point in frame["points"] if point["blanked"]]
    baseline_blanked_points = [point for point in baseline["points"] if point["blanked"]]
    frame_motion = sum(
        abs(current["x"] - previous["x"]) + abs(current["y"] - previous["y"])
        for previous, current in zip(frame["points"], frame_next["points"], strict=True)
    )
    baseline_motion = sum(
        abs(current["x"] - previous["x"]) + abs(current["y"] - previous["y"])
        for previous, current in zip(baseline["points"], baseline_next["points"], strict=True)
    )
    assert lit_points, "section should still emit non-blank ILDA points"
    assert max(point["r"] + point["g"] + point["b"] for point in lit_points) < max(
        point["r"] + point["g"] + point["b"] for point in baseline_lit_points
    )
    assert frame_motion > baseline_motion
    assert blanked_points == []
    assert baseline_blanked_points != []


def test_ilda_output_gap_uses_default_geometry_and_neutral_strobe_bias() -> None:
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
            duration_seconds=20.0,
            show_sections=[
                {
                    "id": "section_000",
                    "start_seconds": 0.0,
                    "end_seconds": 4.0,
                    "laser_enabled": True,
                    "laser_program": {
                        "phrase_role": "drop_variation",
                        "zone_policy": "overhead_only",
                        "launch": {"pattern": "sheet", "geometry_family": "sheet", "bars": 1},
                        "sustain": [{"pattern": "burst", "geometry_family": "burst", "bars": 2}],
                        "fills": [],
                        "release": {"pattern": "trace", "geometry_family": "trace", "bars": 1},
                    },
                },
                {
                    "id": "section_001",
                    "start_seconds": 10.0,
                    "end_seconds": 14.0,
                    "laser_enabled": True,
                    "laser_program": {
                        "phrase_role": "breakdown_release",
                        "zone_policy": "overhead_only",
                        "launch": {"pattern": "fan", "geometry_family": "fan", "bars": 1},
                        "sustain": [{"pattern": "helix", "geometry_family": "helix", "bars": 2}],
                        "fills": [],
                        "release": {"pattern": "trace", "geometry_family": "trace", "bars": 1},
                    },
                },
            ],
        )
    )
    playback.update_transport(
        playhead_seconds=7.0,
        playing=True,
        finished=False,
        realtime=True,
        speed=1.0,
    )

    state = _armed_state()
    state["current_structure"] = MusicStructure.BREAKDOWN
    state["fused_bpm"] = 124.0
    state["beat_info"]["beat_phase"] = 0.05
    state["audio_features"]["timbral_harshness"] = 0.85
    state["director_state"]["laser_aggression"] = 0.35

    try:
        frame = node(state)["ilda_frames"][0]
    finally:
        clear_shared_playback_context()

    assert frame["geometry_family"] == "sky"
    assert any(point["blanked"] for point in frame["points"])


def test_ilda_output_json_export_flushes_latest_snapshot_on_stop(tmp_path: Path) -> None:
    """JSON export should not rewrite the file every 20ms tick. Keep the
    latest payload in memory and flush once on stop()."""
    from photonic_synesthesia.graph.nodes.ilda_output import ILDAExportNode

    fixture = FixtureConfig(
        id="laser-main",
        name="Main Laser",
        type="laser",
        profile="laser_aucd_cx338b_hybrid",
        start_address=1,
        enabled=True,
    )
    export_path = tmp_path / "latest_ilda.json"
    cfg = ILDAConfig(enabled=True, transport_type="json", export_path=export_path, points_per_frame=24)
    node = ILDAOutputNode(
        cfg,
        [fixture],
        LaserSafetyConfig(),
        fixtures_dir=Path("config/fixtures"),
    )
    exporter = ILDAExportNode(cfg)
    node.start()
    state = _armed_state()
    result = node(state)
    result = exporter(result)

    assert result["ilda_frames"]
    assert not export_path.exists()
    exporter.stop()
    assert export_path.exists()
    text = export_path.read_text(encoding="utf-8")
    assert "\"frames\"" in text


def test_encode_ild_writes_truecolor_frame_and_eof_header() -> None:
    payload = encode_ild(
        [
            {
                "fixture_id": "laser-main",
                "profile_name": "laser_aucd_cx338b_hybrid",
                "geometry_family": "burst",
                "color_mode": "white_hits",
                "target_bias": "crowd",
                "point_count": 2,
                "repeat": True,
                "points": [
                    {"x": -100, "y": 100, "r": 255, "g": 0, "b": 0, "blanked": False},
                    {"x": 100, "y": -100, "r": 0, "g": 0, "b": 255, "blanked": True},
                ],
            }
        ]
    )

    assert payload[:4] == b"ILDA"
    assert payload[7] == 5
    assert payload[32:40] != b""
    assert payload[-32:-28] == b"ILDA"
    assert payload[-25] == 5


def test_ilda_output_ild_export_writes_binary_file(tmp_path: Path) -> None:
    """Cycle-5 HIGH: `.ild` export now accumulates in `ILDAExportNode`
    and flushes ONLY on `stop()` (file represents the whole show; the
    old per-tick rewrite was O(N²) and grew memory unbounded). The
    exporter also runs AFTER the interlock chain, so exported frames
    are post-clamp."""
    from photonic_synesthesia.graph.nodes.ilda_output import ILDAExportNode

    fixture = FixtureConfig(
        id="laser-main",
        name="Main Laser",
        type="laser",
        profile="laser_aucd_cx338b_hybrid",
        start_address=1,
        enabled=True,
    )
    export_path = tmp_path / "latest_ilda.ild"
    cfg = ILDAConfig(enabled=True, transport_type="ild", export_path=export_path, points_per_frame=24)
    node = ILDAOutputNode(
        cfg,
        [fixture],
        LaserSafetyConfig(),
        fixtures_dir=Path("config/fixtures"),
    )
    exporter = ILDAExportNode(cfg)
    node.start()
    state = _armed_state()
    result = node(state)
    result = exporter(result)
    # Before flush, nothing on disk yet (timeline is in memory).
    assert not export_path.exists()
    exporter.stop()
    assert result["ilda_frames"]
    assert export_path.exists()
    data = export_path.read_bytes()
    assert data[:4] == b"ILDA"
    assert data[-32:-28] == b"ILDA"


def test_ilda_output_ild_export_accumulates_timeline_frames(tmp_path: Path) -> None:
    """Cycle-5 HIGH: exporter accumulates multi-tick timeline + flushes
    on stop(). Pinning test: consecutive ticks should produce a single
    combined `.ild` file (same end-to-end shape as the pre-refactor
    per-tick rewrite), but the write cost is O(N) at stop() instead of
    O(N²) across the show."""
    from photonic_synesthesia.graph.nodes.ilda_output import ILDAExportNode

    fixture = FixtureConfig(
        id="laser-main",
        name="Main Laser",
        type="laser",
        profile="laser_aucd_cx338b_hybrid",
        start_address=1,
        enabled=True,
    )
    export_path = tmp_path / "timeline.ild"
    cfg = ILDAConfig(enabled=True, transport_type="ild", export_path=export_path, points_per_frame=24)
    node = ILDAOutputNode(
        cfg,
        [fixture],
        LaserSafetyConfig(),
        fixtures_dir=Path("config/fixtures"),
    )
    exporter = ILDAExportNode(cfg)
    node.start()

    first_state = _armed_state()
    first_state["current_structure"] = MusicStructure.BREAKDOWN
    first_result = node(first_state)
    first_result = exporter(first_result)
    first_frames = copy.deepcopy(first_result["ilda_frames"])

    second_state = _armed_state()
    second_state["current_structure"] = MusicStructure.DROP
    second_state["director_state"]["laser_aggression"] = 0.9
    second_result = node(second_state)
    second_result = exporter(second_result)
    second_frames = copy.deepcopy(second_result["ilda_frames"])

    # File only materializes after stop().
    assert not export_path.exists()
    exporter.stop()
    assert export_path.exists()
    data = export_path.read_bytes()

    assert data == encode_ild(first_frames + second_frames)


def test_ilda_transport_streams_to_ether_dream() -> None:
    fixture = FixtureConfig(
        id="laser-main",
        name="Main Laser",
        type="laser",
        profile="laser_aucd_cx338b_hybrid",
        start_address=1,
        enabled=True,
    )
    fake_client = MagicMock()
    with patch("photonic_synesthesia.graph.nodes.ilda_output.EtherDreamClient", return_value=fake_client):
        node = ILDADACOutputNode(
            ILDAConfig(enabled=True, transport_type="ether_dream", target_fps=25.0),
            LaserSafetyConfig(),
            [fixture],
        )
        node.start()
        state = _ilda_state_with_frames([_synthetic_ilda_frame("laser-main", point_count=24)])
        result = node(state)
        node.stop()

    assert result["ilda_frames"]
    fake_client.connect.assert_called_once()
    fake_client.ensure_streaming.assert_called_once()
    args, kwargs = fake_client.ensure_streaming.call_args
    streamed_frame = args[0]
    assert kwargs["point_rate"] == 600
    assert streamed_frame["fixture_id"] == "ilda-composite"
    assert streamed_frame["point_count"] == 24
    fake_client.close.assert_called_once()


def test_ilda_transport_streams_all_ilda_fixtures_to_ether_dream() -> None:
    fixtures = [
        FixtureConfig(
            id="laser-a",
            name="Laser A",
            type="laser",
            profile="laser_aucd_cx338b_hybrid",
            start_address=1,
            enabled=True,
        ),
        FixtureConfig(
            id="laser-b",
            name="Laser B",
            type="laser",
            profile="laser_aucd_cx338b_hybrid",
            start_address=10,
            enabled=True,
        ),
    ]
    fake_client = MagicMock()
    with patch("photonic_synesthesia.graph.nodes.ilda_output.EtherDreamClient", return_value=fake_client):
        node = ILDADACOutputNode(
            ILDAConfig(enabled=True, transport_type="ether_dream", target_fps=25.0),
            LaserSafetyConfig(),
            fixtures,
        )
        node.start()
        state = _ilda_state_with_frames(
            [
                _synthetic_ilda_frame("laser-a", point_count=24),
                _synthetic_ilda_frame("laser-b", point_count=24),
            ]
        )
        result = node(state)
        node.stop()

    assert len(result["ilda_frames"]) == 2
    args, kwargs = fake_client.ensure_streaming.call_args
    streamed_frame = args[0]
    point_sum = sum(frame["point_count"] for frame in result["ilda_frames"])
    assert streamed_frame["fixture_id"] == "ilda-composite"
    assert streamed_frame["point_count"] == point_sum + 1
    assert kwargs["point_rate"] == (point_sum + 1) * 25


def test_ilda_transport_recovers_after_ether_dream_stream_fault() -> None:
    fixture = FixtureConfig(
        id="laser-main",
        name="Main Laser",
        type="laser",
        profile="laser_aucd_cx338b_hybrid",
        start_address=1,
        enabled=True,
    )
    first_client = MagicMock()
    second_client = MagicMock()
    first_client.ensure_streaming.side_effect = OSError("broken pipe")

    with patch(
        "photonic_synesthesia.graph.nodes.ilda_output.EtherDreamClient",
        side_effect=[first_client, second_client],
    ):
        node = ILDADACOutputNode(
            ILDAConfig(enabled=True, transport_type="ether_dream", target_fps=25.0),
            LaserSafetyConfig(),
            [fixture],
        )
        node.start()
        state = _ilda_state_with_frames([_synthetic_ilda_frame("laser-main", point_count=24)])
        node(state)
        assert node.get_stats()["ether_dream_faulted"] is True

        node(state)
        node.stop()

    first_client.connect.assert_called_once()
    first_client.ensure_streaming.assert_called_once()
    first_client.close.assert_called_once()
    second_client.connect.assert_called_once()
    second_client.ensure_streaming.assert_called_once()
    second_client.close.assert_called_once()


def test_ilda_transport_blanks_frames_and_sends_blank_dac_frame() -> None:
    fixture = FixtureConfig(
        id="laser-main",
        name="Main Laser",
        type="laser",
        profile="laser_aucd_cx338b_hybrid",
        start_address=1,
        enabled=True,
    )
    fake_client = MagicMock()
    with patch("photonic_synesthesia.graph.nodes.ilda_output.EtherDreamClient", return_value=fake_client):
        node = ILDADACOutputNode(
            ILDAConfig(enabled=True, transport_type="ether_dream", target_fps=25.0),
            LaserSafetyConfig(),
            [fixture],
        )
        node.start()
        state = _ilda_state_with_frames([_synthetic_ilda_frame("laser-main", point_count=24)])
        node.request_blackout()
        result = node(state)
    node.stop()

    args, kwargs = fake_client.ensure_streaming.call_args
    assert kwargs["point_rate"] == 50
    streamed_frame = args[0]
    assert streamed_frame["geometry_family"] == "composite"
    assert all(point["blanked"] for point in streamed_frame["points"])

    frame = result["ilda_frames"][0]
    assert frame["geometry_family"] == "burst"


def test_ilda_transport_emergency_blackout_streams_repeated_blank_frames() -> None:
    fixture = FixtureConfig(
        id="laser-main",
        name="Main Laser",
        type="laser",
        profile="laser_aucd_cx338b_hybrid",
        start_address=1,
        enabled=True,
    )
    fake_client = MagicMock()
    with patch("photonic_synesthesia.graph.nodes.ilda_output.EtherDreamClient", return_value=fake_client):
        node = ILDADACOutputNode(
            ILDAConfig(enabled=True, transport_type="ether_dream", target_fps=25.0),
            LaserSafetyConfig(ilda_blackout_hold_s=0.08),
            [fixture],
        )
        node.start()
        node.emergency_blackout()
        # Allow background emergency loop to transmit at least a couple frames.
        import time

        time.sleep(0.12)
        node.stop()

    assert fake_client.ensure_streaming.call_count >= 1
    args, _ = fake_client.ensure_streaming.call_args
    streamed_frame = args[0]
    assert streamed_frame["geometry_family"] == "composite"
    assert all(point["blanked"] for point in streamed_frame["points"])


def test_ilda_transport_emergency_blackout_issues_etherdream_emergency_stop() -> None:
    fixture = FixtureConfig(
        id="laser-main",
        name="Main Laser",
        type="laser",
        profile="laser_aucd_cx338b_hybrid",
        start_address=1,
        enabled=True,
    )
    fake_client = MagicMock()
    with patch("photonic_synesthesia.graph.nodes.ilda_output.EtherDreamClient", return_value=fake_client):
        node = ILDADACOutputNode(
            ILDAConfig(enabled=True, transport_type="ether_dream", target_fps=25.0),
            LaserSafetyConfig(),
            [fixture],
        )
        node.start()
        node.emergency_blackout()
        node.stop()

    fake_client.emergency_stop.assert_called()


def test_ilda_transport_clear_blackout_requests_etherdream_clear_emergency() -> None:
    fixture = FixtureConfig(
        id="laser-main",
        name="Main Laser",
        type="laser",
        profile="laser_aucd_cx338b_hybrid",
        start_address=1,
        enabled=True,
    )
    fake_client = MagicMock()
    with patch("photonic_synesthesia.graph.nodes.ilda_output.EtherDreamClient", return_value=fake_client):
        node = ILDADACOutputNode(
            ILDAConfig(enabled=True, transport_type="ether_dream", target_fps=25.0),
            LaserSafetyConfig(),
            [fixture],
        )
        node.start()
        node.emergency_blackout()
        node.clear_blackout_request()
        node.stop()

    fake_client.clear_emergency_stop.assert_called()


def test_ilda_pipeline_enforces_vector_interlock_before_transport() -> None:
    fixture = FixtureConfig(
        id="laser-main",
        name="Main Laser",
        type="laser",
        profile="laser_aucd_cx338b_hybrid",
        start_address=1,
        enabled=True,
    )
    vector_interlock = LaserVectorInterlockNode(
        config=LaserSafetyConfig(
            ilda_x_min=-1000,
            ilda_x_max=1000,
            ilda_y_min=-500,
            ilda_y_max=500,
            ilda_max_point_count=2,
            ilda_min_point_velocity=10,
            ilda_max_point_velocity=10000,
            ilda_max_color_value=120,
            ilda_max_blink_hz=12.0,
        ),
    )
    transport = ILDADACOutputNode(
        ILDAConfig(enabled=True, transport_type="ether_dream", target_fps=25.0),
        LaserSafetyConfig(),
        [fixture],
    )

    unsafe_frames = [
        {
            "fixture_id": "laser-main",
            "profile_name": "laser_aucd_cx338b_hybrid",
            "geometry_family": "fan",
            "color_mode": "white",
            "target_bias": "mid_air",
            "point_count": 3,
            "repeat": True,
            "points": [
                {"x": 20000, "y": 10000, "r": 255, "g": 200, "b": 255, "blanked": False},
                {"x": 30000, "y": 90000, "r": 150, "g": 140, "b": 130, "blanked": False},
                {"x": 0, "y": 0, "r": 60, "g": 70, "b": 80, "blanked": False},
            ],
        }
    ]

    state = _ilda_state_with_frames(unsafe_frames)
    state["beat_info"]["confidence"] = 1.0
    state["timestamp"] = 1.0

    with patch("photonic_synesthesia.graph.nodes.ilda_output.EtherDreamClient") as client_ctor:
        fake_client = MagicMock()
        client_ctor.return_value = fake_client
        transport.start()
        state = vector_interlock(state)
        result = transport(state)

    assert result["ilda_frames"][0]["point_count"] == 2
    sent_frame = fake_client.ensure_streaming.call_args.args[0]

    assert sent_frame["fixture_id"] == "ilda-composite"
    assert sent_frame["point_count"] == 2
    assert sent_frame["points"][0]["x"] == 1000
    assert sent_frame["points"][0]["y"] == 500
    assert sent_frame["points"][0]["r"] == 120
    assert sent_frame["points"][0]["g"] == 120
    assert sent_frame["points"][0]["b"] == 120
    assert sent_frame["points"][1]["blanked"] is True

    transport.stop()


def test_ilda_output_blanks_frames_when_disarmed() -> None:
    fixture = FixtureConfig(
        id="laser-main",
        name="Main Laser",
        type="laser",
        profile="laser_aucd_cx338b_hybrid",
        start_address=1,
        enabled=True,
    )
    node = ILDAOutputNode(
        ILDAConfig(enabled=True, points_per_frame=24),
        [fixture],
        LaserSafetyConfig(),
        fixtures_dir=Path("config/fixtures"),
    )
    state = create_initial_state()

    result = node(state)

    frame = result["ilda_frames"][0]
    assert frame["geometry_family"] == "blank"
    assert all(point["blanked"] for point in frame["points"])
