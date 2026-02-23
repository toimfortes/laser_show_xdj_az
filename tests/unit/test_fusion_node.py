import pytest

from photonic_synesthesia.core.state import create_initial_state
from photonic_synesthesia.graph.nodes.fusion import FusionNode


def test_fusion_high_pass_attenuates_low_and_mid_bands() -> None:
    state = create_initial_state()
    state["audio_features"]["low_energy"] = 1.0
    state["audio_features"]["mid_energy"] = 1.0
    state["audio_features"]["high_energy"] = 1.0
    state["midi_state"]["filter_positions"] = [1.0, 1.0, 1.0, 1.0]  # heavy HPF

    result = FusionNode()(state)

    assert result["rule_stream"]["low_band"] == pytest.approx(0.2)
    assert result["rule_stream"]["mid_band"] == pytest.approx(0.65)
    assert result["rule_stream"]["high_band"] == 1.0


def test_fusion_low_pass_attenuates_high_and_mid_bands() -> None:
    state = create_initial_state()
    state["audio_features"]["low_energy"] = 1.0
    state["audio_features"]["mid_energy"] = 1.0
    state["audio_features"]["high_energy"] = 1.0
    state["midi_state"]["filter_positions"] = [0.0, 0.0, 0.0, 0.0]  # heavy LPF

    result = FusionNode()(state)

    assert result["rule_stream"]["low_band"] == 1.0
    assert result["rule_stream"]["mid_band"] == pytest.approx(0.75)
    assert result["rule_stream"]["high_band"] == pytest.approx(0.2)
