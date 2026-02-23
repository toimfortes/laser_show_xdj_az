from __future__ import annotations

import time

from photonic_synesthesia.core.config import (
    FixtureConfig,
    LaserSafetyConfig,
    SafetyConfig,
    StrobeSafetyConfig,
)
from photonic_synesthesia.core.state import FixtureCommand, create_initial_state
from photonic_synesthesia.dmx.universe import create_universe_buffer
from photonic_synesthesia.graph.nodes.safety_interlock import SafetyInterlockNode


class _DMXBlackoutProbe:
    def __init__(self) -> None:
        self.blackouts = 0

    def blackout(self) -> None:
        self.blackouts += 1


class _DMXBlackoutRequestProbe(_DMXBlackoutProbe):
    def __init__(self) -> None:
        super().__init__()
        self.requested = 0

    def request_blackout(self) -> None:
        self.requested += 1


def test_safety_interlock_uses_configured_laser_offsets() -> None:
    fixture = FixtureConfig(
        id="laser-1",
        name="Laser 1",
        type="laser",
        profile="laser_generic_7ch",
        start_address=100,
        enabled=True,
    )
    safety = SafetyConfig(
        laser=LaserSafetyConfig(
            y_axis_max=100,
            min_scan_speed=30,
            y_channel_offset=1,
            speed_channel_offset=2,
        )
    )
    node = SafetyInterlockNode(config=safety, fixtures=[fixture])

    state = create_initial_state()
    universe = create_universe_buffer()
    universe[101] = 240  # configured y offset
    universe[102] = 5  # configured speed offset
    universe[104] = 240  # old hardcoded y offset (+4) should be untouched
    state["dmx_universe"] = bytes(universe)
    state["beat_info"]["confidence"] = 1.0

    result = node(state)
    result_universe = result["dmx_universe"]

    assert result_universe[101] == 100
    assert result_universe[102] == 30
    assert result_universe[104] == 240


def test_heartbeat_watchdog_triggers_blackout_on_timeout() -> None:
    safety = SafetyConfig(heartbeat_timeout_s=0.05)
    dmx_probe = _DMXBlackoutProbe()
    node = SafetyInterlockNode(config=safety, fixtures=[], dmx_output=dmx_probe)

    node.start()
    deadline = time.monotonic() + 0.5
    try:
        while dmx_probe.blackouts == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        node.stop()

    assert dmx_probe.blackouts >= 1


def test_heartbeat_watchdog_prefers_request_blackout_when_available() -> None:
    safety = SafetyConfig(heartbeat_timeout_s=0.05)
    dmx_probe = _DMXBlackoutRequestProbe()
    node = SafetyInterlockNode(config=safety, fixtures=[], dmx_output=dmx_probe)

    node.start()
    deadline = time.monotonic() + 0.5
    try:
        while dmx_probe.requested == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        node.stop()

    assert dmx_probe.requested >= 1
    assert dmx_probe.blackouts == 0


def test_strobe_duration_limit_enters_cooldown_and_suppresses_strobe_channels() -> None:
    fixture = FixtureConfig(
        id="mover-1",
        name="Mover 1",
        type="moving_head",
        profile="moving_head_16ch",
        start_address=20,
        enabled=True,
    )
    safety = SafetyConfig(
        strobe=StrobeSafetyConfig(
            max_rate_hz=50.0,
            max_duration_s=0.01,
            cooldown_s=1.0,
        )
    )
    node = SafetyInterlockNode(config=safety, fixtures=[fixture])

    state = create_initial_state()
    state["beat_info"]["confidence"] = 1.0
    state["timestamp"] = 1000.0
    state["fixture_commands"] = [
        FixtureCommand(
            fixture_id="mover-1",
            fixture_type="moving_head",
            channel_values={26: 255},  # moving-head strobe channel (base + 6)
        )
    ]
    universe = create_universe_buffer()
    universe[26] = 255
    state["dmx_universe"] = bytes(universe)
    node(state)

    state = create_initial_state()
    state["beat_info"]["confidence"] = 1.0
    state["timestamp"] = 1000.02
    state["fixture_commands"] = [
        FixtureCommand(
            fixture_id="mover-1",
            fixture_type="moving_head",
            channel_values={26: 255},
        )
    ]
    universe = create_universe_buffer()
    universe[26] = 255
    state["dmx_universe"] = bytes(universe)
    result = node(state)

    assert result["fixture_commands"][0]["channel_values"][26] == 0
    assert result["dmx_universe"][26] == 0
    assert result["safety_state"]["strobe_enabled"] is False


def test_graceful_degradation_scales_output_on_low_beat_confidence() -> None:
    safety = SafetyConfig(min_beat_confidence=0.8, graceful_degradation=True)
    node = SafetyInterlockNode(config=safety, fixtures=[])

    state = create_initial_state()
    state["beat_info"]["confidence"] = 0.1
    state["fixture_commands"] = [
        FixtureCommand(
            fixture_id="panel-1",
            fixture_type="panel",
            channel_values={50: 200},
        )
    ]
    universe = create_universe_buffer()
    universe[50] = 200
    state["dmx_universe"] = bytes(universe)
    result = node(state)

    # scale = max(0.35, 0.1 / 0.8) = 0.35
    assert result["fixture_commands"][0]["channel_values"][50] == 70
    assert result["dmx_universe"][50] == 70


def test_graceful_degradation_keeps_laser_mode_channel_unchanged() -> None:
    fixture = FixtureConfig(
        id="laser-1",
        name="Laser 1",
        type="laser",
        profile="laser_generic_7ch",
        start_address=1,
        enabled=True,
    )
    safety = SafetyConfig(min_beat_confidence=0.8, graceful_degradation=True)
    node = SafetyInterlockNode(config=safety, fixtures=[fixture])

    state = create_initial_state()
    state["beat_info"]["confidence"] = 0.1
    state["fixture_commands"] = [
        FixtureCommand(
            fixture_id="laser-1",
            fixture_type="laser",
            channel_values={
                1: 200,  # laser mode channel must stay in DMX/manual range
                7: 180,  # zoom may be scaled
            },
        )
    ]
    result = node(state)

    assert result["fixture_commands"][0]["channel_values"][1] == 200
    assert result["fixture_commands"][0]["channel_values"][7] == 62
