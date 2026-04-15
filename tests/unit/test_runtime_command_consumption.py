from unittest import mock

from photonic_synesthesia.core.config import Settings
from photonic_synesthesia.core.state import create_initial_state
from photonic_synesthesia.graph.builder import PhotonicGraph
from photonic_synesthesia.platform import CommandType, ControlPlaneStateService, OperatorCommand, OperatorRole


class _IdentityGraph:
    def invoke(self, state):  # type: ignore[override]
        return state


def test_graph_consumes_blackout_command_and_requests_dmx_blackout() -> None:
    service = ControlPlaneStateService()
    dmx_output = mock.MagicMock()
    graph = PhotonicGraph(
        graph=_IdentityGraph(),
        settings=Settings(),
        nodes={"dmx_output": dmx_output},
        control_plane_service=service,
    )

    service.accept_command(
        OperatorCommand(
            issuer_id="alice",
            session_id="sess-1",
            role=OperatorRole.OPERATOR,
            command_type=CommandType.BLACKOUT,
        )
    )

    graph.step()

    assert graph.state["control_state"]["blackout_active"] is True
    dmx_output.request_blackout.assert_called_once()


def test_graph_consumes_scene_launch_and_hold_commands() -> None:
    service = ControlPlaneStateService()
    graph = PhotonicGraph(
        graph=_IdentityGraph(),
        settings=Settings(),
        nodes={},
        control_plane_service=service,
    )
    graph._state = create_initial_state()
    graph._state["scene_state"]["current_scene"] = "idle"

    service.accept_command(
        OperatorCommand(
            issuer_id="alice",
            session_id="sess-1",
            role=OperatorRole.OPERATOR,
            command_type=CommandType.LAUNCH_SCENE,
            payload={"scene_id": "intro_ambient"},
        )
    )
    service.accept_command(
        OperatorCommand(
            issuer_id="alice",
            session_id="sess-1",
            role=OperatorRole.OPERATOR,
            command_type=CommandType.HOLD_SCENE,
            payload={"scene_id": "drop_intense"},
        )
    )

    graph.step()

    assert graph.state["control_state"]["launched_scene"] == "intro_ambient"
    assert graph.state["control_state"]["scene_hold"] == "drop_intense"
