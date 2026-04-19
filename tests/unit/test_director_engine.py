from photonic_synesthesia.core.state import MusicStructure, create_initial_state
from photonic_synesthesia.director import DirectorEngine
from photonic_synesthesia.graph.nodes.director_intent import DirectorIntentNode


def test_director_holds_scene_until_phrase_boundary() -> None:
    state = create_initial_state()
    state["current_structure"] = MusicStructure.DROP
    state["audio_features"]["rms_energy"] = 0.9
    state["rule_stream"]["transient"] = 0.9
    state["beat_info"]["downbeat"] = False
    state["beat_info"]["bar_position"] = 2

    director = DirectorEngine()
    decision = director.decide(state)

    assert decision.allow_scene_transition is False
    assert decision.target_scene == "idle"

    state["beat_info"]["downbeat"] = True
    state["beat_info"]["bar_position"] = 1
    decision = director.decide(state)

    assert decision.allow_scene_transition is True
    assert decision.target_scene == "drop_intense"


def test_director_prefers_ml_scene_when_confident() -> None:
    state = create_initial_state()
    state["beat_info"]["downbeat"] = True
    state["beat_info"]["bar_position"] = 1
    state["ml_stream"]["predicted_scene"] = "custom_peak_scene"
    state["ml_stream"]["confidence"] = 0.85

    decision = DirectorEngine().decide(state)

    assert decision.target_scene == "custom_peak_scene"


def test_director_energy_is_bounded() -> None:
    state = create_initial_state()
    state["audio_features"]["rms_energy"] = 3.0
    state["rule_stream"]["transient"] = 2.0
    state["beat_info"]["confidence"] = 1.0

    decision = DirectorEngine().decide(state)

    assert 0.0 <= decision.energy_level <= 1.0
    assert 0.0 <= decision.melodic_smoothness <= 1.0
    assert 0.0 <= decision.laser_aggression <= 1.0
    assert 0.0 <= decision.color_drive <= 1.0
    assert 0.0 <= decision.laser_motion_energy <= 1.0
    assert 0.0 <= decision.laser_color_energy <= 1.0
    assert 0.0 <= decision.fill_pressure <= 1.0
    assert 0.0 <= decision.phrase_intensity <= 1.1


def test_director_intent_node_publishes_extended_director_fields() -> None:
    state = create_initial_state()
    state["current_structure"] = MusicStructure.DROP
    state["audio_features"]["harmonic_ratio"] = 0.65
    state["audio_features"]["percussive_ratio"] = 0.72
    state["audio_features"]["tonal_stability"] = 0.58
    state["audio_features"]["harmonic_change"] = 0.48
    state["audio_features"]["pitch_salience"] = 0.61
    state["audio_features"]["pitch_height"] = 0.55
    state["audio_features"]["timbral_harshness"] = 0.74
    state["audio_features"]["spectral_flux"] = 0.69

    result = DirectorIntentNode()(state)

    assert "melodic_smoothness" in result["director_state"]
    assert "laser_aggression" in result["director_state"]
    assert "color_drive" in result["director_state"]
    assert "laser_motion_energy" in result["director_state"]
    assert "laser_color_energy" in result["director_state"]
    assert "phrase_role" in result["director_state"]
    assert "subphrase_role" in result["director_state"]
    assert "fill_pressure" in result["director_state"]
    assert "phrase_intensity" in result["director_state"]
    assert 0.0 <= result["director_state"]["melodic_smoothness"] <= 1.0
    assert 0.0 <= result["director_state"]["laser_aggression"] <= 1.0
    assert 0.0 <= result["director_state"]["color_drive"] <= 1.0
    assert 0.0 <= result["director_state"]["laser_motion_energy"] <= 1.0
    assert 0.0 <= result["director_state"]["laser_color_energy"] <= 1.0
    assert 0.0 <= result["director_state"]["fill_pressure"] <= 1.0
    assert 0.0 <= result["director_state"]["phrase_intensity"] <= 1.1


def test_director_drop_launch_settles_after_structure_ages() -> None:
    state = create_initial_state()
    state["current_structure"] = MusicStructure.DROP
    state["fused_bpm"] = 128.0
    state["audio_features"]["percussive_ratio"] = 0.78
    state["audio_features"]["harmonic_tension"] = 0.42
    state["audio_features"]["onset_density"] = 0.3
    state["rule_stream"]["transient"] = 0.75

    state["time_since_structure_change"] = 1.0
    launch = DirectorEngine().decide(state)

    state["time_since_structure_change"] = 8.0
    settle = DirectorEngine().decide(state)

    assert launch.subphrase_role == "launch"
    assert settle.subphrase_role in {"settle", "groove", "variation"}
    assert launch.phrase_intensity > settle.phrase_intensity
