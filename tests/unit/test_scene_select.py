import json
from pathlib import Path

from photonic_synesthesia.core.config import SceneConfig
from photonic_synesthesia.core.state import MusicStructure, create_initial_state
from photonic_synesthesia.graph.nodes.scene_select import SceneSelectNode


def _write_scene(path: Path, scene_id: str) -> None:
    (path / f"{scene_id}.json").write_text(
        json.dumps(
            {
                "name": scene_id,
                "triggers": {"energy_threshold": 0.25},
            }
        )
    )


def test_scene_select_follows_director_target_when_valid(tmp_path: Path) -> None:
    _write_scene(tmp_path, "idle")
    _write_scene(tmp_path, "drop_intense")
    state = create_initial_state()
    state["scene_state"]["current_scene"] = "idle"
    state["director_state"]["target_scene"] = "drop_intense"
    state["director_state"]["allow_scene_transition"] = True

    node = SceneSelectNode(SceneConfig(scenes_dir=tmp_path))
    result = node(state)

    assert result["scene_state"]["pending_scene"] == "drop_intense"
    assert result["scene_state"]["current_scene"] == "idle"
    assert result["processing_times"]["scene_select"] >= 0.0


def test_scene_select_honors_director_transition_gate(tmp_path: Path) -> None:
    _write_scene(tmp_path, "drop_intense")
    _write_scene(tmp_path, "intro_ambient")

    state = create_initial_state()
    state["current_structure"] = MusicStructure.DROP
    state["scene_state"]["current_scene"] = "drop_intense"
    state["director_state"]["target_scene"] = "intro_ambient"
    state["director_state"]["allow_scene_transition"] = False

    node = SceneSelectNode(SceneConfig(scenes_dir=tmp_path))
    result = node(state)

    assert result["scene_state"]["current_scene"] == "drop_intense"
    assert result["scene_state"]["pending_scene"] is None


def test_scene_select_falls_back_when_director_is_unknown(tmp_path: Path) -> None:
    _write_scene(tmp_path, "drop_intense")
    _write_scene(tmp_path, "intro_ambient")

    state = create_initial_state()
    state["current_structure"] = MusicStructure.DROP
    state["scene_state"]["current_scene"] = "intro_ambient"
    state["director_state"]["target_scene"] = "not_a_scene"
    state["director_state"]["allow_scene_transition"] = True

    node = SceneSelectNode(SceneConfig(scenes_dir=tmp_path))
    result = node(state)

    # Fallback for DROP should remain to loaded drop-intense scene.
    assert result["scene_state"]["pending_scene"] == "drop_intense"


def test_scene_select_prefers_scene_hold_over_director_target(tmp_path: Path) -> None:
    _write_scene(tmp_path, "idle")
    _write_scene(tmp_path, "drop_intense")
    _write_scene(tmp_path, "intro_ambient")

    state = create_initial_state()
    state["scene_state"]["current_scene"] = "drop_intense"
    state["control_state"]["scene_hold"] = "intro_ambient"
    state["director_state"]["target_scene"] = "drop_intense"

    node = SceneSelectNode(SceneConfig(scenes_dir=tmp_path))
    result = node(state)

    assert result["scene_state"]["pending_scene"] == "intro_ambient"
