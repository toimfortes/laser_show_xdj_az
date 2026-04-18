from __future__ import annotations

import copy

from photonic_synesthesia.core.config import LaserSafetyConfig
from photonic_synesthesia.core.state import PhotonicState, create_initial_state
from photonic_synesthesia.graph.nodes.laser_vector_interlock import LaserVectorInterlockNode


def _interlock_state() -> tuple[PhotonicState, LaserVectorInterlockNode]:
    state = create_initial_state()
    state["timestamp"] = 1.0
    state["beat_info"]["confidence"] = 1.0
    config = LaserSafetyConfig(
        ilda_x_min=-1000,
        ilda_x_max=1000,
        ilda_y_min=-1000,
        ilda_y_max=1000,
        ilda_max_point_count=3,
        ilda_min_point_velocity=10,
        ilda_max_point_velocity=100,
        ilda_max_color_value=200,
        ilda_max_blink_hz=1.0,
    )
    return state, LaserVectorInterlockNode(config=config)


def test_laser_vector_interlock_caps_points_and_coordinates() -> None:
    state, node = _interlock_state()
    state["ilda_frames"] = [
        {
            "fixture_id": "laser-1",
            "profile_name": "profile",
            "geometry_family": "fan",
            "color_mode": "white",
            "target_bias": "mid_air",
            "point_count": 4,
            "repeat": True,
            "points": [
                {"x": 2000, "y": -1500, "r": 255, "g": 255, "b": 255, "blanked": False},
                {"x": -2000, "y": 5000, "r": 255, "g": 255, "b": 255, "blanked": False},
                {"x": 0, "y": 0, "r": 50, "g": 50, "b": 50, "blanked": True},
                {"x": 9000, "y": 9000, "r": 255, "g": 100, "b": 0, "blanked": False},
            ],
        }
    ]

    result = node(state)
    frame = result["ilda_frames"][0]

    assert frame["point_count"] == 3
    assert len(frame["points"]) == 3
    assert all(-1000 <= point["x"] <= 1000 for point in frame["points"])
    assert all(-1000 <= point["y"] <= 1000 for point in frame["points"])
    assert all(point["r"] <= 200 for point in frame["points"])
    assert all(point["g"] <= 200 for point in frame["points"])
    assert all(point["b"] <= 200 for point in frame["points"])


def test_laser_vector_interlock_enforces_min_velocity_floor_for_standing_bright_points() -> None:
    state, node = _interlock_state()
    state["ilda_frames"] = [
        {
            "fixture_id": "laser-1",
            "profile_name": "profile",
            "geometry_family": "fan",
            "color_mode": "white",
            "target_bias": "mid_air",
            "point_count": 2,
            "repeat": True,
            "points": [
                {"x": 0, "y": 0, "r": 180, "g": 180, "b": 180, "blanked": False},
                {"x": 5, "y": 5, "r": 180, "g": 180, "b": 180, "blanked": False},
            ],
        }
    ]

    result = node(state)
    points = result["ilda_frames"][0]["points"]

    assert points[0]["blanked"] is False
    assert points[1]["blanked"] is True


def test_laser_vector_interlock_scales_excessive_point_velocity() -> None:
    state, node = _interlock_state()
    state["ilda_frames"] = [
        {
            "fixture_id": "laser-1",
            "profile_name": "profile",
            "geometry_family": "fan",
            "color_mode": "white",
            "target_bias": "mid_air",
            "point_count": 2,
            "repeat": True,
            "points": [
                {"x": 0, "y": 0, "r": 64, "g": 64, "b": 64, "blanked": False},
                {"x": 10000, "y": 0, "r": 64, "g": 64, "b": 64, "blanked": False},
            ],
        }
    ]

    result = node(state)
    points = result["ilda_frames"][0]["points"]

    assert points[0]["blanked"] is False
    assert abs(points[1]["x"] - 0) <= 100
    assert abs(points[1]["y"] - 0) <= 100


def test_laser_vector_interlock_applies_blink_rate_limit() -> None:
    state, node = _interlock_state()
    config = LaserSafetyConfig(
        ilda_min_point_velocity=10,
        ilda_max_point_velocity=1000,
        ilda_max_blink_hz=1.0,
        ilda_max_point_count=1,
    )

    base_frame = {
        "fixture_id": "laser-1",
        "profile_name": "profile",
        "geometry_family": "fan",
        "color_mode": "white",
        "target_bias": "mid_air",
        "point_count": 1,
        "repeat": True,
        "points": [
            {"x": 0, "y": 0, "r": 64, "g": 64, "b": 64, "blanked": False},
        ],
    }
    # Recreate node with blink-specific config.
    node = LaserVectorInterlockNode(config=config)

    results = []
    for index, offset in enumerate([0.0, 0.1, 0.2], start=0):
        state["timestamp"] = 10.0 + offset
        frame = copy.deepcopy(base_frame)
        frame["points"][0]["x"] = index * 20
        frame["points"][0]["blanked"] = index == 1
        state["ilda_frames"] = [frame]
        results.append(node(state)["ilda_frames"][0]["points"][0]["blanked"])

    assert results[0] is False
    assert results[1] is True
    assert results[2] is True
