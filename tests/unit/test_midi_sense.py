from photonic_synesthesia.core.config import MidiConfig
from photonic_synesthesia.core.state import create_initial_state
from photonic_synesthesia.graph.nodes.midi_sense import MidiSenseNode


def test_midi_sense_tracks_eq_and_effect_hints() -> None:
    node = MidiSenseNode(MidiConfig())
    # Drive all channels into high-pass style filter range.
    for channel in (1, 2, 3, 4):
        node._handle_cc(node.midi_map.CHANNEL_FILTERS[channel], 127)
    node._handle_cc(node.midi_map.EQ_HI[1], 127)
    # Ch2 bass cut
    node._handle_cc(node.midi_map.EQ_LO[2], 0)

    state = create_initial_state()
    result = node(state)

    assert result["midi_state"]["eq_positions"]["hi"][0] == 1.0
    assert result["midi_state"]["eq_positions"]["lo"][1] == 0.0
    assert "high_pass_sweep" in result["midi_state"]["active_effects"]
    assert "hi_boost" in result["midi_state"]["active_effects"]
    assert "bass_cut" in result["midi_state"]["active_effects"]
