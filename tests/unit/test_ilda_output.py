from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from photonic_synesthesia.core.config import FixtureConfig, ILDAConfig, LaserSafetyConfig
from photonic_synesthesia.core.state import MusicStructure, create_initial_state
from photonic_synesthesia.graph.nodes.ilda_output import ILDAOutputNode
from photonic_synesthesia.laser.ilda_file import encode_ild


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
    state = create_initial_state()
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


def test_ilda_output_json_export_writes_frame_snapshot(tmp_path: Path) -> None:
    fixture = FixtureConfig(
        id="laser-main",
        name="Main Laser",
        type="laser",
        profile="laser_aucd_cx338b_hybrid",
        start_address=1,
        enabled=True,
    )
    export_path = tmp_path / "latest_ilda.json"
    node = ILDAOutputNode(
        ILDAConfig(enabled=True, transport_type="json", export_path=export_path, points_per_frame=24),
        [fixture],
        LaserSafetyConfig(),
        fixtures_dir=Path("config/fixtures"),
    )
    node.start()
    state = create_initial_state()
    result = node(state)

    assert result["ilda_frames"]
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
    fixture = FixtureConfig(
        id="laser-main",
        name="Main Laser",
        type="laser",
        profile="laser_aucd_cx338b_hybrid",
        start_address=1,
        enabled=True,
    )
    export_path = tmp_path / "latest_ilda.ild"
    node = ILDAOutputNode(
        ILDAConfig(enabled=True, transport_type="ild", export_path=export_path, points_per_frame=24),
        [fixture],
        LaserSafetyConfig(),
        fixtures_dir=Path("config/fixtures"),
    )
    node.start()
    state = create_initial_state()
    result = node(state)

    assert result["ilda_frames"]
    assert export_path.exists()
    data = export_path.read_bytes()
    assert data[:4] == b"ILDA"
    assert data[-32:-28] == b"ILDA"


def test_ilda_output_streams_to_ether_dream_transport() -> None:
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
        node = ILDAOutputNode(
            ILDAConfig(enabled=True, transport_type="ether_dream", points_per_frame=16, target_fps=25.0),
            [fixture],
            LaserSafetyConfig(),
            fixtures_dir=Path("config/fixtures"),
        )
        node.start()
        state = create_initial_state()
        result = node(state)
        node.stop()

    assert result["ilda_frames"]
    fake_client.connect.assert_called_once()
    fake_client.ensure_streaming.assert_called_once()
    _, kwargs = fake_client.ensure_streaming.call_args
    assert kwargs["point_rate"] == 600
    fake_client.close.assert_called_once()
