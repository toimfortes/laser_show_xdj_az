from fastapi.testclient import TestClient

from photonic_synesthesia.core.state import create_initial_state
from photonic_synesthesia.platform import ControlPlaneStateService
from photonic_synesthesia.ui.web_panel import create_app


def test_create_app_exposes_core_control_plane_routes() -> None:
    app = create_app()
    routes = {route.path for route in app.routes}

    assert "/" in routes
    assert "/healthz" in routes
    assert "/api/live/health" in routes
    assert "/api/live/state" in routes
    assert "/api/control/lease/acquire" in routes
    assert "/api/control/blackout" in routes
    assert "/api/control/scenes/launch" in routes
    assert "/api/control/scenes/hold" in routes


def test_live_state_endpoint_reflects_runtime_ingest() -> None:
    services = ControlPlaneStateService()
    state = create_initial_state()
    state["scene_state"]["current_scene"] = "intro_ambient"
    services.update_from_photonic_state(state)

    app = create_app(services=services)
    client = TestClient(app)

    response = client.get("/api/live/state")

    assert response.status_code == 200
    body = response.json()
    assert body["active_scene_id"] == "intro_ambient"
    assert body["diagnostics"]["runtime_source"] == "graph"
