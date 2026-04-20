"""Task 4 frontend acceptance: operator-workspace endpoints + HTML anchor.

Pins the cycle-N invariants on the API surface added in Task 4 frontend:
- GET /api/operator/workspace returns the cycle-2-cached
  `operator_workspace_banks` (NOT the cycle-1 `operator_workspace`
  fallback) plus the live `active_scene_id` from the snapshot's
  per-call overlay (cycle-3 panel 3C-H1 + UF-7).
- POST /api/operator/stage routes to PlaybackContext.set_staged_look
  with preview-only semantics (cycle-1 panel UF-11).
- POST /api/operator/commit deep-merges + clears (cycle-1 panel UF-12);
  fails closed with 409 when the playhead advanced past the staged
  section's end (cycle-1 panel SF-1).
- The inline HTML at `_render_control_plane_html()` carries the
  `<div id="operator-workspace">` anchor that mock_control_plane.js
  binds to (cycle-1 panel UF-32).
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from photonic_synesthesia.platform.runtime_context import (  # noqa: E402
    PlaybackContext,
    clear_shared_playback_context,
    set_shared_playback_context,
)
from photonic_synesthesia.ui.web_panel import (  # noqa: E402
    _render_control_plane_html,
    create_app,
)


@pytest.fixture()
def client_with_session(tmp_path):
    """Spin up the web app with a populated PlaybackContext + two sections."""
    ctx = PlaybackContext(
        file_path=str(tmp_path / "x.wav"),
        file_name="x.wav",
        duration_seconds=60.0,
    )
    ctx.replace_show_sections([
        {
            "id": "sec-0", "label": "Intro", "section_role": "intro",
            "start_seconds": 0.0, "end_seconds": 30.0,
            "cue_recipe": {"phasers": [{"family": "breathing"}]},
            "laser_program": {"zone_policy": "overhead_only", "fills": [{"label": "Fill A"}]},
            "tags": ["role:intro"],
        },
        {
            "id": "sec-1", "label": "Drop", "section_role": "drop_1",
            "start_seconds": 30.0, "end_seconds": 60.0,
            "cue_recipe": {}, "laser_program": {}, "tags": ["role:drop_1"],
        },
    ])
    ctx.update_transport(
        playhead_seconds=10.0, playing=True, finished=False, realtime=True, speed=1.0,
    )
    set_shared_playback_context(ctx)
    try:
        yield TestClient(create_app()), ctx
    finally:
        clear_shared_playback_context()


def test_workspace_endpoint_returns_banks_and_live_active_scene_id(client_with_session) -> None:
    """Cycle-3 panel 3C-H1 + cycle-1 panel UF-7."""
    client, _ctx = client_with_session
    response = client.get("/api/operator/workspace")
    assert response.status_code == 200
    body = response.json()
    bank_ids = [b["id"] for b in body["banks"]]
    assert bank_ids == ["scene", "safety", "tags"]
    scene_buttons = [b["id"] for b in body["banks"][0]["buttons"]]
    assert scene_buttons == ["scene:sec-0", "scene:sec-1"]
    # active_scene_id from live overlay (playhead 10s → sec-0).
    assert body["active_scene_id"] == "sec-0"


def test_workspace_endpoint_active_scene_follows_playhead(client_with_session) -> None:
    """Cycle-1 panel UF-7: active_scene_id is per-call overlay, not cached."""
    client, ctx = client_with_session
    ctx.update_transport(
        playhead_seconds=45.0, playing=True, finished=False, realtime=True, speed=1.0,
    )
    body = client.get("/api/operator/workspace").json()
    assert body["active_scene_id"] == "sec-1"


def test_stage_then_commit_deep_merges_authored_section(client_with_session) -> None:
    """Cycle-1 panel UF-11 + UF-12."""
    client, ctx = client_with_session
    stage_resp = client.post("/api/operator/stage", json={
        "section_id": "sec-0",
        "cue_recipe": {"phasers": [{"family": "sweep"}]},
        "laser_program": {"zone_policy": "mixed_air"},
    })
    assert stage_resp.status_code == 200
    staged = stage_resp.json()
    assert staged["section_id"] == "sec-0"
    assert staged["committed"] is False

    commit_resp = client.post("/api/operator/commit")
    assert commit_resp.status_code == 200
    committed = commit_resp.json()
    assert committed["committed"] is True
    # Operator override took effect.
    assert ctx.show_sections[0]["cue_recipe"]["phasers"][0]["family"] == "sweep"
    assert ctx.show_sections[0]["laser_program"]["zone_policy"] == "mixed_air"
    # Authored fields the operator did NOT touch survived (deep-merge).
    assert ctx.show_sections[0]["laser_program"]["fills"][0]["label"] == "Fill A"


def test_commit_without_staged_look_returns_400(client_with_session) -> None:
    client, _ctx = client_with_session
    response = client.post("/api/operator/commit")
    assert response.status_code == 400


def test_commit_after_playhead_past_section_returns_409(client_with_session) -> None:
    """Cycle-1 panel SF-1: fail closed when playhead crossed section end."""
    client, ctx = client_with_session
    client.post("/api/operator/stage", json={
        "section_id": "sec-0", "cue_recipe": {}, "laser_program": {},
    })
    ctx.update_transport(
        playhead_seconds=45.0, playing=True, finished=False, realtime=True, speed=1.0,
    )
    response = client.post("/api/operator/commit")
    assert response.status_code == 409
    assert "playhead" in response.json()["detail"].lower()


def test_workspace_endpoint_returns_empty_when_no_active_session() -> None:
    """No PlaybackContext → empty banks (no crash, no 500)."""
    clear_shared_playback_context()
    client = TestClient(create_app())
    response = client.get("/api/operator/workspace")
    assert response.status_code == 200
    assert response.json() == {"banks": [], "active_scene_id": ""}


def test_html_carries_operator_workspace_anchor() -> None:
    """Cycle-1 panel UF-32 / cycle-5 inline-HTML clarification: shipped
    UI uses inline HTML in web_panel.py (no Jinja templates)."""
    html = _render_control_plane_html()
    assert 'id="operator-workspace"' in html
    assert "Operator Workspace" in html
