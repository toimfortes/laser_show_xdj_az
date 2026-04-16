from fastapi.testclient import TestClient

from photonic_synesthesia.core.state import create_initial_state
from photonic_synesthesia.platform import (
    ControlPlaneStateService,
    PlaybackContext,
    clear_shared_playback_context,
    get_shared_playback_context,
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
    assert "/api/mock/playback/ilda-export" in routes
    assert "/api/mock/playback/seek" in routes
    assert "/api/mock/fixtures" in routes
    assert "/api/mock/scene" in routes
    assert "/api/mock/masters" in routes


def test_live_state_endpoint_reflects_runtime_ingest() -> None:
    services = ControlPlaneStateService()
    state = create_initial_state()
    state["scene_state"]["current_scene"] = "intro_ambient"
    state["ilda_frames"] = [
        {
            "fixture_id": "laser-main",
            "profile_name": "laser_aucd_cx338b_hybrid",
            "geometry_family": "burst",
            "color_mode": "white_hits",
            "target_bias": "crowd",
            "point_count": 2,
            "repeat": True,
            "points": [],
        }
    ]
    services.update_from_photonic_state(state)

    app = create_app(services=services)
    client = TestClient(app)

    response = client.get("/api/live/state")

    assert response.status_code == 200
    body = response.json()
    assert body["active_scene_id"] == "intro_ambient"
    assert body["diagnostics"]["runtime_source"] == "graph"
    assert body["diagnostics"]["ilda_frame_count"] == 1
    assert body["diagnostics"]["ilda_geometry_families"] == ["burst"]


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
    ilda_path = tmp_path / "track.ild"
    ilda_path.write_bytes(b"ILDAdemo")

    clear_shared_playback_context()
    shared_playback = set_shared_playback_context(
        PlaybackContext(
            file_path=str(audio_path),
            file_name=audio_path.name,
            track_title="Relax Your Mind",
            track_artist="19_26, Yubik",
            duration_seconds=12.5,
            track_key="19_26|Relax Your Mind",
            waveform=[0.1, 0.5, 0.2],
            show_plan_path=str(tmp_path / "show_plan.json"),
            ilda_transport_type="ild",
            ilda_export_path=str(ilda_path),
            hardware_warnings=["Laser 'laser-main' is using inferred adapter data."],
            structure_markers=[
                {"name": "Intro E:6", "kind": "intro", "start_seconds": 0.0, "energy_hint": 6},
                {"name": "Drop E:8", "kind": "drop", "start_seconds": 4.0, "energy_hint": 8},
            ],
            show_sections=[
                {
                    "id": "section_000",
                    "label": "Intro E:6",
                    "kind": "intro",
                    "start_seconds": 0.0,
                    "end_seconds": 4.0,
                    "scene_id": "intro_ambient",
                    "fixture_mode": "intro",
                    "intensity_multiplier": 0.75,
                    "motion_multiplier": 0.6,
                    "strobe_level": 0.0,
                    "laser_enabled": False,
                    "movers_enabled": True,
                    "washes_enabled": True,
                    "leds_enabled": False,
                }
            ],
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
    ilda_response = client.get(metadata["ilda_export_url"])
    stale_audio_response = client.get("/api/mock/playback/audio?session=stale-session")

    assert metadata_response.status_code == 200
    assert metadata["available"] is True
    assert metadata["file_name"] == "track.mp3"
    assert metadata["track_title"] == "Relax Your Mind"
    assert metadata["track_artist"] == "19_26, Yubik"
    assert metadata["track_key"] == "19_26|Relax Your Mind"
    assert metadata["waveform"] == [0.1, 0.5, 0.2]
    assert metadata["ilda_transport_type"] == "ild"
    assert metadata["ilda_export_available"] is True
    assert metadata["hardware_warnings"] == ["Laser 'laser-main' is using inferred adapter data."]
    assert len(metadata["structure_markers"]) == 2
    assert metadata["show_sections"][0]["scene_id"] == "intro_ambient"
    assert metadata["playhead_seconds"] == 3.25
    assert metadata["playing"] is True
    assert metadata["session_id"] == shared_playback.session_id
    assert metadata["audio_url"].endswith(shared_playback.session_id)
    assert metadata["transport_revision"] == 1
    assert audio_response.status_code == 200
    assert audio_response.content == b"fake mp3 bytes"
    assert ilda_response.status_code == 200
    assert ilda_response.content == b"ILDAdemo"
    assert stale_audio_response.status_code == 404

    clear_shared_playback_context()


def test_playback_show_section_update_round_trips_through_backend(tmp_path) -> None:
    audio_path = tmp_path / "track.mp3"
    audio_path.write_bytes(b"fake mp3 bytes")

    clear_shared_playback_context()
    saved_payloads: list[dict[str, object]] = []
    playback = set_shared_playback_context(
        PlaybackContext(
            file_path=str(audio_path),
            file_name=audio_path.name,
            duration_seconds=12.5,
            track_key="artist|track",
            show_sections=[
                {
                    "id": "section_001",
                    "label": "Drop E:8",
                    "kind": "drop",
                    "start_seconds": 4.0,
                    "end_seconds": 8.0,
                    "scene_id": "drop_intense",
                    "fixture_mode": "peak_return",
                    "intensity_multiplier": 1.0,
                    "motion_multiplier": 1.0,
                    "strobe_level": 0.2,
                    "laser_enabled": True,
                    "movers_enabled": True,
                    "washes_enabled": True,
                    "leds_enabled": True,
                    "laser_expression": {
                        "content_family": "transition",
                        "target_strategy": "drop_launch_fan",
                        "blanking_strategy": "impact_gates",
                        "color_strategy": "white_accent_launch",
                        "phrase_envelope": {
                            "launch_intensity": 1.05,
                            "sustain_intensity": 0.64,
                            "release_intensity": 0.42,
                        },
                        "variation_plan": ["hit hard", "settle down"],
                    },
                }
            ],
            _save_callback=lambda payload: saved_payloads.append(payload) or str(tmp_path / "saved.json"),
        )
    )

    app = create_app()
    client = TestClient(app)
    response = client.patch(
        "/api/mock/playback/show-sections/section_001",
        json={
            "changes": {
                "scene_id": "break_sweep",
                "motion_multiplier": 1.45,
                "laser_enabled": False,
                "laser_expression.content_family": "abstract",
                "laser_expression.target_strategy": "aerial_hold",
                "laser_expression.phrase_envelope.sustain_intensity": 0.55,
                "laser_expression.variation_plan": "reduce beam density\nuse overhead arcs",
            }
        },
    )

    assert response.status_code == 200
    updated = response.json()["show_sections"][0]
    assert updated["scene_id"] == "break_sweep"
    assert updated["motion_multiplier"] == 1.45
    assert updated["laser_enabled"] is False
    assert updated["laser_expression"]["content_family"] == "abstract"
    assert updated["laser_expression"]["target_strategy"] == "aerial_hold"
    assert updated["laser_expression"]["phrase_envelope"]["sustain_intensity"] == 0.55
    assert updated["laser_expression"]["variation_plan"] == [
        "reduce beam density",
        "use overhead arcs",
    ]
    assert get_shared_playback_context() is playback
    assert saved_payloads
    assert saved_payloads[-1]["track_key"] == "artist|track"

    clear_shared_playback_context()


def test_playback_seek_endpoint_updates_shared_playhead(tmp_path) -> None:
    audio_path = tmp_path / "track.mp3"
    audio_path.write_bytes(b"fake mp3 bytes")

    clear_shared_playback_context()
    playback = set_shared_playback_context(
        PlaybackContext(
            file_path=str(audio_path),
            file_name=audio_path.name,
            duration_seconds=20.0,
            _seek_callback=lambda seconds: float(seconds),
        )
    )
    playback.update_transport(
        playhead_seconds=0.0,
        playing=True,
        finished=False,
        realtime=True,
        speed=1.0,
    )

    app = create_app()
    client = TestClient(app)
    response = client.post("/api/mock/playback/seek", json={"seconds": 7.5})

    assert response.status_code == 200
    assert response.json()["playhead_seconds"] == 7.5
    assert get_shared_playback_context() is playback
    assert playback.snapshot()["playhead_seconds"] == 7.5

    clear_shared_playback_context()
    set_shared_playback_context(
        PlaybackContext(
            file_path=str(audio_path),
            file_name=audio_path.name,
            duration_seconds=12.5,
            show_sections=[
                {
                    "id": "section_001",
                    "label": "Drop E:8",
                    "kind": "drop",
                    "start_seconds": 4.0,
                    "end_seconds": 8.0,
                    "scene_id": "drop_intense",
                    "fixture_mode": "peak_return",
                    "intensity_multiplier": 1.0,
                    "motion_multiplier": 1.0,
                    "strobe_level": 0.2,
                    "laser_enabled": True,
                    "movers_enabled": True,
                    "washes_enabled": True,
                    "leds_enabled": True,
                }
            ],
        )
    )

    app = create_app()
    client = TestClient(app)
    response = client.patch(
        "/api/mock/playback/show-sections/section_001",
        json={
            "changes": {
                "scene_id": "break_sweep",
                "motion_multiplier": 1.45,
                "laser_enabled": False,
            }
        },
    )

    assert response.status_code == 200
    updated = response.json()["show_sections"][0]
    assert updated["scene_id"] == "break_sweep"
    assert updated["motion_multiplier"] == 1.45
    assert updated["laser_enabled"] is False

    clear_shared_playback_context()
