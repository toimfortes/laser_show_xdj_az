from __future__ import annotations

from photonic_synesthesia.core.config import DMXConfig
from photonic_synesthesia.core.state import create_initial_state
from photonic_synesthesia.dmx.universe import (
    DMX_CHANNEL_COUNT,
    DMX_START_CODE,
    DMX_START_CODE_INDEX,
    DMX_UNIVERSE_SIZE,
    create_universe_buffer,
    extract_channel_payload,
)
from photonic_synesthesia.graph.nodes.dmx_output import DMXOutputNode


def test_create_universe_buffer_contract() -> None:
    universe = create_universe_buffer()
    assert len(universe) == DMX_UNIVERSE_SIZE
    assert universe[DMX_START_CODE_INDEX] == DMX_START_CODE


def test_extract_channel_payload_contract() -> None:
    universe = create_universe_buffer()
    universe[1] = 11
    universe[512] = 99

    payload = extract_channel_payload(bytes(universe))
    assert len(payload) == DMX_CHANNEL_COUNT
    assert payload[0] == 11
    assert payload[-1] == 99


def test_dmx_output_ignores_out_of_range_channels() -> None:
    node = DMXOutputNode(DMXConfig(interface_type="artnet"))
    state = create_initial_state()
    state["fixture_commands"] = [
        {
            "fixture_id": "fx1",
            "fixture_type": "laser",
            "channel_values": {
                0: 200,
                1: 123,
                513: 200,
            },
        }
    ]

    result = node(state)
    universe = result["dmx_universe"]

    assert universe[1] == 123
    assert universe[0] == DMX_START_CODE
    assert universe[512] == 0
