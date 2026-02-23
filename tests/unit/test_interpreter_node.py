from photonic_synesthesia.core.config import Settings
from photonic_synesthesia.core.state import FixtureCommand, create_initial_state
from photonic_synesthesia.graph.nodes.interpreter import InterpreterNode


def test_interpreter_enforces_laser_safety_constraints() -> None:
    settings = Settings()
    node = InterpreterNode(settings.safety, max_delta_per_frame=255)
    state = create_initial_state()
    state["director_state"]["strobe_budget_hz"] = 0.0
    state["fixture_commands"] = [
        FixtureCommand(
            fixture_id="laser1",
            fixture_type="laser",
            channel_values={
                1: 200,
                4: 220,  # Y axis channel (base + 3)
                5: 10,  # Scan speed channel (base + 4)
            },
        )
    ]

    result = node(state)
    cmd = result["fixture_commands"][0]

    assert cmd["channel_values"][4] <= settings.safety.laser.y_axis_max
    assert cmd["channel_values"][5] >= settings.safety.laser.min_scan_speed


def test_interpreter_rate_limits_channel_changes() -> None:
    settings = Settings()
    node = InterpreterNode(settings.safety, max_delta_per_frame=10)
    state = create_initial_state()
    state["fixture_commands"] = [
        FixtureCommand(
            fixture_id="panel1",
            fixture_type="panel",
            channel_values={50: 200},
        )
    ]

    result = node(state)
    assert result["fixture_commands"][0]["channel_values"][50] == 10

    state = create_initial_state()
    state["fixture_commands"] = [
        FixtureCommand(
            fixture_id="panel1",
            fixture_type="panel",
            channel_values={50: 200},
        )
    ]
    result = node(state)
    assert result["fixture_commands"][0]["channel_values"][50] == 20


def test_interpreter_caps_strobe_from_director_budget() -> None:
    settings = Settings()
    node = InterpreterNode(settings.safety, max_delta_per_frame=255)
    state = create_initial_state()
    state["director_state"]["strobe_budget_hz"] = 0.0
    state["fixture_commands"] = [
        FixtureCommand(
            fixture_id="mover1",
            fixture_type="moving_head",
            channel_values={
                20: 150,
                26: 255,  # Moving-head strobe channel (base + 6)
            },
        )
    ]

    result = node(state)
    assert result["fixture_commands"][0]["channel_values"][26] == 0
