from __future__ import annotations

import time

from photonic_synesthesia.core.config import FixtureConfig, LaserSafetyConfig, SafetyConfig
from photonic_synesthesia.core.state import create_initial_state
from photonic_synesthesia.dmx.universe import create_universe_buffer
from photonic_synesthesia.graph.nodes.safety_interlock import SafetyInterlockNode


class _DMXBlackoutProbe:
    def __init__(self) -> None:
        self.blackouts = 0

    def blackout(self) -> None:
        self.blackouts += 1


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
