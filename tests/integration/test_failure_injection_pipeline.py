from __future__ import annotations

from unittest import mock

from photonic_synesthesia.core.config import DMXConfig, Settings
from photonic_synesthesia.core.state import FixtureCommand, PhotonicState, create_initial_state
from photonic_synesthesia.graph.builder import PhotonicGraph, _SequentialPipeline
from photonic_synesthesia.graph.nodes.dmx_output import DMXOutputNode
from photonic_synesthesia.platform import (
    CommandType,
    ControlPlaneStateService,
    InMemoryCommandBus,
    OperatorCommand,
    OperatorRole,
)


class _ProgramActiveState:
    def __call__(self, state: PhotonicState) -> PhotonicState:
        state["fixture_commands"] = [
            FixtureCommand(
                fixture_id="panel-1",
                fixture_type="panel",
                channel_values={1: 255},
            )
        ]
        return state


class _IdentityGraph:
    def invoke(self, state):  # type: ignore[override]
        return state


def test_dead_watchdog_blackouts_dmx_on_next_graph_step() -> None:
    """If the watchdog is already dead, the current step surfaces the fault
    and the very next frame must render blackout."""
    dmx_output = DMXOutputNode(DMXConfig(interface_type="artnet"))
    nodes = {
        "program": _ProgramActiveState(),
        "dmx_output": dmx_output,
    }
    graph = PhotonicGraph(
        graph=_SequentialPipeline(["program", "dmx_output"], nodes),
        settings=Settings(),
        nodes=nodes,
    )
    graph._state = create_initial_state()
    graph._state["control_state"]["armed_live"] = True
    graph._watchdog_proc = mock.MagicMock(pid=99999)
    graph._watchdog_proc.is_alive.side_effect = lambda: False
    graph._watchdog_faulted = False

    first = graph.step()
    first_channel = first["dmx_universe"][1]
    second = graph.step()

    assert first_channel == 255
    assert second["dmx_universe"][1] == 0
    assert graph._watchdog_faulted is True
    assert dmx_output.get_stats()["blackout_requested"] is True


def test_rejected_command_overload_does_not_mutate_graph_control_state() -> None:
    """Backpressure must reject excess commands without applying their effects."""
    service = ControlPlaneStateService()
    service.commands = InMemoryCommandBus(max_queue=1)
    graph = PhotonicGraph(
        graph=_IdentityGraph(),
        settings=Settings(),
        nodes={},
        control_plane_service=service,
    )
    graph._state = create_initial_state()

    accepted = service.accept_command(
        OperatorCommand(
            issuer_id="alice",
            session_id="sess-1",
            role=OperatorRole.OPERATOR,
            command_type=CommandType.ARM,
        )
    )
    rejected = service.accept_command(
        OperatorCommand(
            issuer_id="alice",
            session_id="sess-1",
            role=OperatorRole.OPERATOR,
            command_type=CommandType.DISARM,
        )
    )

    state = graph.step()

    assert accepted.accepted is True
    assert rejected.accepted is False
    assert state["control_state"]["armed_live"] is True
    assert state["control_state"]["blackout_active"] is False
    assert service.commands.backlog() == 0
