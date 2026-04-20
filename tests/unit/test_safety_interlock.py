from __future__ import annotations

import threading
import time

from photonic_synesthesia.core.config import (
    FixtureConfig,
    LaserSafetyConfig,
    SafetyConfig,
    StrobeSafetyConfig,
)
from photonic_synesthesia.core.state import FixtureCommand, create_initial_state
from photonic_synesthesia.dmx.universe import create_universe_buffer
from photonic_synesthesia.graph.nodes.safety_interlock import SafetyInterlockNode, SafetyMonitor


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


class _EmergencyBlackoutProbe(_DMXBlackoutProbe):
    def __init__(self) -> None:
        super().__init__()
        self.emergency = 0

    def emergency_blackout(self) -> None:
        self.emergency += 1


class _FrameCounterProbe:
    def __init__(self, running: bool = True, fixture_count: int = 1) -> None:
        self.running = running
        self.fixture_count = fixture_count
        self.frames_sent = 0
        self.blackouts = 0
        self.requests = 0
        self.emergency = 0

    def get_stats(self) -> dict[str, int | float | bool | str | None]:
        return {
            "running": self.running,
            "fixture_count": self.fixture_count,
            "frames_sent": self.frames_sent,
        }

    def blackout(self) -> None:
        self.blackouts += 1

    def request_blackout(self) -> None:
        self.requests += 1

    def emergency_blackout(self) -> None:
        self.emergency += 1


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


def test_heartbeat_watchdog_triggers_all_outputs_when_available() -> None:
    safety = SafetyConfig(heartbeat_timeout_s=0.05)
    dmx_probe = _DMXBlackoutRequestProbe()
    ilda_probe = _EmergencyBlackoutProbe()
    node = SafetyInterlockNode(config=safety, fixtures=[], dmx_output=dmx_probe, ilda_output=ilda_probe)

    node.start()
    deadline = time.monotonic() + 0.5
    try:
        while (dmx_probe.requested == 0 and ilda_probe.emergency == 0) and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        node.stop()

    assert dmx_probe.requested >= 1
    assert ilda_probe.emergency >= 1


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


def test_safety_monitor_triggers_blackout_on_stalled_dmx_output() -> None:
    dmx_output = _FrameCounterProbe()
    monitor = SafetyMonitor(dmx_output=dmx_output, check_interval=0.02, max_silence=0.08)

    monitor.start()
    try:
        deadline = time.monotonic() + 0.5
        while dmx_output.blackouts == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        monitor.stop()

    assert dmx_output.blackouts >= 1 or dmx_output.emergency >= 1 or dmx_output.requests >= 1


def test_safety_monitor_blackout_applies_to_all_outputs_on_stall() -> None:
    dmx_output = _FrameCounterProbe()
    ilda_output = _FrameCounterProbe()
    monitor = SafetyMonitor(
        dmx_output=dmx_output,
        ilda_output=ilda_output,
        check_interval=0.02,
        max_silence=0.08,
    )

    # Cycle-6 C3: use threading.Event instead of a plain bool so the
    # bump thread wakes immediately on stop (not on the next 20ms
    # sleep boundary) and the pattern matches M1 conventions.
    stop_event = threading.Event()

    def bump_dmx() -> None:
        while not stop_event.is_set():
            stop_event.wait(0.02)
            dmx_output.frames_sent += 1

    thread = None
    try:
        thread = threading.Thread(target=bump_dmx, daemon=True)
        thread.start()

        monitor.start()
        deadline = time.monotonic() + 0.5
        while (
            dmx_output.blackouts == 0
            and dmx_output.emergency == 0
            and dmx_output.requests == 0
            and ilda_output.blackouts == 0
            and ilda_output.emergency == 0
            and ilda_output.requests == 0
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
    finally:
        stop_event.set()
        if thread is not None:
            thread.join(timeout=0.5)
            assert not thread.is_alive(), "bump_dmx leaked past stop signal"
        monitor.stop()

    assert (
        dmx_output.blackouts >= 1
        or dmx_output.emergency >= 1
        or dmx_output.requests >= 1
    )
    assert (
        ilda_output.blackouts >= 1
        or ilda_output.emergency >= 1
        or ilda_output.requests >= 1
    )


def test_safety_monitor_skips_inactive_output() -> None:
    probe = _FrameCounterProbe(running=False, fixture_count=0)
    monitor = SafetyMonitor(dmx_output=probe, check_interval=0.02, max_silence=0.05)

    monitor.start()
    try:
        time.sleep(0.2)
    finally:
        monitor.stop()

    assert probe.blackouts == 0
    assert probe.emergency == 0
    assert probe.requests == 0
