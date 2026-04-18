from __future__ import annotations

from unittest.mock import MagicMock, patch

from photonic_synesthesia.core.config import FixtureConfig, ILDAConfig, LaserSafetyConfig
from photonic_synesthesia.core.state import ILDAPoint, create_initial_state
from photonic_synesthesia.graph.nodes.ilda_output import ILDADACOutputNode
from photonic_synesthesia.graph.nodes.laser_vector_interlock import LaserVectorInterlockNode


def _unsafe_ilda_frame() -> dict:
    return {
        "fixture_id": "laser-main",
        "profile_name": "laser_aucd_cx338b_hybrid",
        "geometry_family": "burst",
        "color_mode": "white",
        "target_bias": "crowd",
        "point_count": 4,
        "repeat": True,
        "points": [
            {"x": 50_000, "y": 40_000, "r": 255, "g": 200, "b": 245, "blanked": False},
            {"x": 50_100, "y": 40_200, "r": 245, "g": 230, "b": 200, "blanked": False},
            {"x": 51_000, "y": 39_800, "r": 255, "g": 255, "b": 255, "blanked": False},
            {"x": 0, "y": 0, "r": 0, "g": 0, "b": 0, "blanked": True},
        ],
    }


def _safe_state_with_unsafe_frame(frame: dict) -> dict:
    state = create_initial_state()
    state["control_state"]["armed_live"] = True
    state["timestamp"] = 2.0
    state["beat_info"]["confidence"] = 1.0
    state["ilda_frames"] = [frame]
    return state


def _fixture() -> FixtureConfig:
    return FixtureConfig(
        id="laser-main",
        name="Main Laser",
        type="laser",
        profile="laser_aucd_cx338b_hybrid",
        start_address=1,
        enabled=True,
    )


def test_ilda_hazards_are_clamped_before_dac_output() -> None:
    fixture = _fixture()
    vector_interlock = LaserVectorInterlockNode(
        config=LaserSafetyConfig(
            ilda_x_min=-1_000,
            ilda_x_max=1_000,
            ilda_y_min=-2_000,
            ilda_y_max=2_000,
            ilda_max_point_count=3,
            ilda_max_color_value=180,
            ilda_min_point_velocity=10,
            ilda_max_point_velocity=100_000,
            ilda_max_blink_hz=12.0,
        ),
    )
    transport = ILDADACOutputNode(
        ILDAConfig(enabled=True, transport_type="ether_dream", target_fps=25.0),
        LaserSafetyConfig(),
        [fixture],
    )
    state = _safe_state_with_unsafe_frame(_unsafe_ilda_frame())
    with patch("photonic_synesthesia.graph.nodes.ilda_output.EtherDreamClient", return_value=MagicMock()) as ctor:
        fake_client = ctor.return_value
        transport.start()
        interlocked_state = vector_interlock(state)
        transport(interlocked_state)
        transport.stop()

    assert len(interlocked_state["ilda_frames"]) == 1
    assert interlocked_state["ilda_frames"][0]["point_count"] == 3
    sent_frame = fake_client.ensure_streaming.call_args.args[0]
    assert sent_frame["geometry_family"] == "composite"
    assert sent_frame["point_count"] == 3

    sent_points = sent_frame["points"]
    assert len(sent_points) == 3
    assert all(-1_000 <= point["x"] <= 1_000 for point in sent_points)
    assert all(-2_000 <= point["y"] <= 2_000 for point in sent_points)
    assert all(0 <= point["r"] <= 180 for point in sent_points)
    assert all(0 <= point["g"] <= 180 for point in sent_points)
    assert all(0 <= point["b"] <= 180 for point in sent_points)
    assert sent_points[0]["blanked"] is False
    assert any(point["blanked"] for point in sent_points)
