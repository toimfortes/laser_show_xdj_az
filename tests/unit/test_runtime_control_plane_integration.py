from unittest import mock

from photonic_synesthesia.core.state import create_initial_state
from photonic_synesthesia.platform import (
    ControlPlaneStateService,
    clear_shared_control_plane_service,
    get_shared_control_plane_service,
    set_shared_control_plane_service,
)
from photonic_synesthesia.ui.web_panel import create_app


def test_photonic_graph_step_publishes_snapshot_to_control_plane_service() -> None:
    from photonic_synesthesia.graph.builder import PhotonicGraph

    class _FakeGraph:
        def invoke(self, state):  # type: ignore[override]
            state = create_initial_state()
            state["scene_state"]["current_scene"] = "drop_intense"
            state["frame_number"] = 7
            return state

    service = ControlPlaneStateService()
    graph = PhotonicGraph(
        graph=_FakeGraph(),
        settings=mock.MagicMock(),
        nodes={},
        control_plane_service=service,
    )

    snapshot = graph.step()

    assert snapshot["scene_state"]["current_scene"] == "drop_intense"
    assert service.snapshot().active_scene_id == "drop_intense"
    assert service.snapshot().diagnostics["frame_number"] == 7


def test_web_panel_uses_shared_control_plane_service_by_default() -> None:
    clear_shared_control_plane_service()
    shared = set_shared_control_plane_service(ControlPlaneStateService())
    shared.update_from_photonic_state(create_initial_state(), source="shared_test")

    app = create_app()

    assert app.state.services is shared
    assert get_shared_control_plane_service() is shared

    clear_shared_control_plane_service()
