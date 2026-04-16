from fastapi.testclient import TestClient

from photonic_synesthesia.core.state import create_initial_state
from photonic_synesthesia.platform import (
    ControlPlaneStateService,
    PlaybackContext,
    clear_shared_playback_context,
    set_shared_playback_context,
)
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
    assert "/api/mock/catalog" in routes
    assert "/api/mock/state" in routes
    assert "/api/mock/universes" in routes
    assert "/api/mock/playback" in routes
    assert "/api/mock/playback/audio" in routes
    assert "/api/mock/fixtures" in routes
    assert "/api/mock/scene" in routes
    assert "/api/mock/masters" in routes


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


def test_root_page_exposes_mock_visualizer_shell() -> None:
    app = create_app()
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "Control Plane Mock Visualizer" in response.text
    assert "/static/mock_control_plane.js" in response.text


def test_mock_catalog_exposes_fixture_and_scene_templates() -> None:
    app = create_app()
    client = TestClient(app)

    response = client.get("/api/mock/catalog")

    assert response.status_code == 200
    body = response.json()
    assert body["fixture_templates"]
    assert body["scene_templates"]
    assert body["default_rig"]
    assert {item["slug"] for item in body["fixture_templates"]} >= {
        "laser",
        "moving_head",
        "wash",
        "led_bar",
    }


def test_mock_rig_crud_round_trips_through_backend_state() -> None:
    app = create_app()
    client = TestClient(app)

    initial_state = client.get("/api/mock/state")
    assert initial_state.status_code == 200
    initial_count = len(initial_state.json()["fixtures"])

    create_response = client.post("/api/mock/fixtures", json={"template_slug": "laser"})
    assert create_response.status_code == 200
    created_fixture = create_response.json()["fixture"]
    assert created_fixture["type"] == "laser"

    update_response = client.patch(
        f"/api/mock/fixtures/{created_fixture['id']}",
        json={"changes": {"universe": 3, "address": 101, "x": 0.55}},
    )
    assert update_response.status_code == 200
    updated_fixture = update_response.json()["fixture"]
    assert updated_fixture["universe"] == 3
    assert updated_fixture["address"] == 101

    duplicate_response = client.post(f"/api/mock/fixtures/{created_fixture['id']}/duplicate")
    assert duplicate_response.status_code == 200
    assert duplicate_response.json()["fixture"]["id"] != created_fixture["id"]

    delete_response = client.delete(f"/api/mock/fixtures/{created_fixture['id']}")
    assert delete_response.status_code == 200

    final_state = client.get("/api/mock/state")
    assert final_state.status_code == 200
    assert len(final_state.json()["fixtures"]) == initial_count + 1


def test_mock_universe_snapshot_includes_sparse_channel_monitor() -> None:
    app = create_app()
    client = TestClient(app)

    create_response = client.post("/api/mock/fixtures", json={"template_slug": "wash"})
    fixture_id = create_response.json()["fixture"]["id"]
    patch_response = client.patch(
        f"/api/mock/fixtures/{fixture_id}",
        json={"changes": {"universe": 4, "address": 120, "color": "#3366ff"}},
    )
    assert patch_response.status_code == 200

    response = client.get("/api/mock/universes")

    assert response.status_code == 200
    body = response.json()
    target_universe = next(item for item in body["universes"] if item["universe"] == 4)
    assert target_universe["active_channel_count"] >= 4
    first_channel = target_universe["channels"][0]
    assert first_channel["channel"] == 120
    assert first_channel["fixture_label"]


def test_live_websocket_streams_snapshot_payload() -> None:
    app = create_app()
    client = TestClient(app)

    with client.websocket_connect("/ws/live") as websocket:
        payload = websocket.receive_json()

    assert payload["snapshot_id"]
    assert "captured_at" in payload


def test_playback_endpoint_exposes_shared_audio_metadata(tmp_path) -> None:
    audio_path = tmp_path / "track.mp3"
    audio_path.write_bytes(b"fake mp3 bytes")

    clear_shared_playback_context()
    shared_playback = set_shared_playback_context(
        PlaybackContext(
            file_path=str(audio_path),
            file_name=audio_path.name,
            duration_seconds=12.5,
            waveform=[0.1, 0.5, 0.2],
        )
    )
    shared_playback.update_transport(
        playhead_seconds=3.25,
        playing=True,
        finished=False,
        realtime=True,
        speed=1.0,
    )

    app = create_app()
    client = TestClient(app)

    metadata_response = client.get("/api/mock/playback")
    metadata = metadata_response.json()
    audio_response = client.get(metadata["audio_url"])
    stale_audio_response = client.get("/api/mock/playback/audio?session=stale-session")

    assert metadata_response.status_code == 200
    assert metadata["available"] is True
    assert metadata["file_name"] == "track.mp3"
    assert metadata["waveform"] == [0.1, 0.5, 0.2]
    assert metadata["playhead_seconds"] == 3.25
    assert metadata["playing"] is True
    assert metadata["session_id"] == shared_playback.session_id
    assert metadata["audio_url"].endswith(shared_playback.session_id)
    assert metadata["transport_revision"] == 1
    assert audio_response.status_code == 200
    assert audio_response.content == b"fake mp3 bytes"
    assert stale_audio_response.status_code == 404

    clear_shared_playback_context()
