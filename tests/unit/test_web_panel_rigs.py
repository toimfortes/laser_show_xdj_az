"""End-to-end tests for the rig-storage web endpoints.

Each test pins one Cycle-1 panel finding so a future refactor cannot
silently re-introduce the defect.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from photonic_synesthesia.platform import rig_storage  # noqa: E402
from photonic_synesthesia.ui.web_panel import create_app  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_rigs_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def fixtures_dir(tmp_path):
    fdir = tmp_path / "fixtures"
    fdir.mkdir()
    (fdir / "laser_generic_9ch.yaml").write_text(
        yaml.safe_dump({"name": "Generic 9CH", "type": "laser", "channels": 9}),
        encoding="utf-8",
    )
    (fdir / "laser_generic_7ch.yaml").write_text(
        yaml.safe_dump({"name": "Generic 7CH", "type": "laser", "channels": 7}),
        encoding="utf-8",
    )
    return fdir


@pytest.fixture
def client(fixtures_dir):
    return TestClient(create_app(fixtures_dir=fixtures_dir))


def _laser_fixture(fid="laser-1", *, address=1, profile="laser_generic_9ch", enabled=True):
    return {
        "id": fid,
        "label": fid.upper(),
        "templateSlug": "laser",
        "type": "laser",
        "x": 0.18,
        "y": 0.16,
        "color": "#12d8ff",
        "intensity": 0.9,
        "spread": 0.3,
        "beam_count": 5,
        "swing": 0.4,
        "universe": 1,
        "address": address,
        "profile": profile,
        "enabled": enabled,
    }


# ---------------------------------------------------------------------------
# Listing


def test_get_rigs_empty_returns_empty_list_with_null_active(client):
    r = client.get("/api/mock/rigs")
    assert r.status_code == 200
    assert r.json() == {"rigs": [], "active": None}


# ---------------------------------------------------------------------------
# PUT round-trip


def test_put_then_get_round_trips_full_document(client):
    fixtures = [_laser_fixture("a"), _laser_fixture("b", address=20)]
    r = client.put("/api/mock/rigs/antonios_lights", json={"fixtures": fixtures})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "antonios_lights"
    assert len(body["fixtures"]) == 2
    assert body["_schema_version"] == rig_storage.RIG_SCHEMA_VERSION
    assert body["saved_at"].endswith("Z")

    g = client.get("/api/mock/rigs/antonios_lights")
    assert g.status_code == 200
    g_body = g.json()
    assert [f["id"] for f in g_body["fixtures"]] == ["a", "b"]


def test_put_strips_client_supplied_schema_version_and_saved_at(client):
    """Cycle-1 panel A10: server-stamped fields cannot be forged via PUT."""
    fixtures = [_laser_fixture()]
    # Even if the client tries to send these (they're rejected by the
    # request model since the schema doesn't include them — they're
    # silently dropped).
    r = client.put(
        "/api/mock/rigs/test_rig",
        json={
            "fixtures": fixtures,
            "_schema_version": 99,  # ignored
            "saved_at": "1970-01-01T00:00:00Z",  # ignored
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["_schema_version"] == rig_storage.RIG_SCHEMA_VERSION
    assert not body["saved_at"].startswith("1970")


# ---------------------------------------------------------------------------
# Snapshot endpoint (Cycle-1 panel Codex H#2 — separate from PUT)


def test_post_snapshot_captures_current_mockrig_state(client):
    """The snapshot endpoint dumps the current MockRigStore into a
    named rig file. Verifies it sees the seeded default rig."""
    r = client.post("/api/mock/rigs/snap_test/snapshot")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "snap_test"
    assert len(body["fixtures"]) > 0  # default rig has fixtures


# ---------------------------------------------------------------------------
# Load endpoint (Cycle-1 panel Claude M5 — clear_selection)


def test_post_load_replaces_mockrigstore_and_clears_selection(client):
    fixtures = [_laser_fixture("loaded-a"), _laser_fixture("loaded-b", address=30)]
    client.put("/api/mock/rigs/loadme", json={"fixtures": fixtures})
    r = client.post("/api/mock/rigs/loadme/load")
    assert r.status_code == 200
    body = r.json()
    assert body["loaded"] == "loadme"
    assert body["clear_selection"] is True
    assert {f["id"] for f in body["state"]["fixtures"]} == {"loaded-a", "loaded-b"}


def test_post_load_404_for_missing_rig(client):
    r = client.post("/api/mock/rigs/never_existed/load")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Activate (Cycle-1 panel Claude L2 — refuses dangling pointer)


def test_post_activate_refuses_404_when_target_missing(client):
    r = client.post("/api/mock/rigs/never_existed/activate")
    assert r.status_code == 404


def test_post_activate_sets_pointer_when_rig_exists(client):
    fixtures = [_laser_fixture()]
    client.put("/api/mock/rigs/active_me", json={"fixtures": fixtures})
    r = client.post("/api/mock/rigs/active_me/activate")
    assert r.status_code == 200
    list_r = client.get("/api/mock/rigs")
    assert list_r.json()["active"] == "active_me"


# ---------------------------------------------------------------------------
# Delete + force (Cycle-1 panel Kilo H2)


def test_delete_active_rig_without_force_returns_409(client):
    client.put("/api/mock/rigs/keep_me", json={"fixtures": [_laser_fixture()]})
    client.post("/api/mock/rigs/keep_me/activate")
    r = client.delete("/api/mock/rigs/keep_me")
    assert r.status_code == 409


def test_delete_active_rig_with_force_clears_active_pointer_atomically(client):
    """Cycle-1 panel Kilo H2: force-deleting the active rig MUST
    atomically clear `_active.json` so no stale pointer is left."""
    client.put("/api/mock/rigs/doomed", json={"fixtures": [_laser_fixture()]})
    client.post("/api/mock/rigs/doomed/activate")
    r = client.delete("/api/mock/rigs/doomed?force=true")
    assert r.status_code == 200
    body = r.json()
    assert body["deleted"] == "doomed"
    assert body["active"] is None


def test_delete_404_for_missing_rig(client):
    r = client.delete("/api/mock/rigs/never_existed")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Profile / enabled persistence (Cycle-1 panel Kilo CRITICAL#3)


def test_patch_fixture_profile_persists(client):
    """Cycle-1 panel Kilo CRITICAL#3: PATCH must actually persist the
    `profile` key. Previously the whitelist silently dropped it."""
    state = client.get("/api/mock/state").json()
    target = state["fixtures"][0]
    fid = target["id"]
    r = client.patch(
        f"/api/mock/fixtures/{fid}",
        json={"changes": {"profile": "laser_generic_7ch"}},
    )
    assert r.status_code == 200
    assert r.json()["fixture"]["profile"] == "laser_generic_7ch"
    # Round-trip via GET to prove persistence.
    re_state = client.get("/api/mock/state").json()
    re_target = next(f for f in re_state["fixtures"] if f["id"] == fid)
    assert re_target["profile"] == "laser_generic_7ch"


def test_patch_fixture_enabled_persists(client):
    state = client.get("/api/mock/state").json()
    target = state["fixtures"][0]
    fid = target["id"]
    r = client.patch(
        f"/api/mock/fixtures/{fid}",
        json={"changes": {"enabled": False}},
    )
    assert r.status_code == 200
    assert r.json()["fixture"]["enabled"] is False
    re_state = client.get("/api/mock/state").json()
    re_target = next(f for f in re_state["fixtures"] if f["id"] == fid)
    assert re_target["enabled"] is False


def test_patch_fixture_profile_null_clears_it(client):
    """Setting profile=null is valid (visual-only)."""
    state = client.get("/api/mock/state").json()
    fid = state["fixtures"][0]["id"]
    r = client.patch(
        f"/api/mock/fixtures/{fid}",
        json={"changes": {"profile": None}},
    )
    assert r.status_code == 200
    assert r.json()["fixture"].get("profile") is None


# ---------------------------------------------------------------------------
# Profile listing (Cycle-1 panel Codex H#3)


def test_get_fixture_profiles_uses_settings_fixtures_dir(client, fixtures_dir):
    """Cycle-1 panel Codex H#3: the dropdown MUST reflect the same dir
    the runtime uses, NOT a hardcoded `config/fixtures`."""
    r = client.get("/api/mock/fixture-profiles")
    assert r.status_code == 200
    body = r.json()
    assert body["fixtures_dir"] == str(fixtures_dir)
    slugs = {p["slug"] for p in body["profiles"]}
    assert {"laser_generic_9ch", "laser_generic_7ch"} <= slugs


# ---------------------------------------------------------------------------
# Conflict detection in response payload


def test_address_conflict_warnings_in_response_payload_non_blocking(client):
    """Conflicts are surfaced in the response, NOT raised as 4xx, so
    the user can save WIP layouts and fix them in the UI."""
    bad_fixtures = [
        _laser_fixture("a", address=1),
        _laser_fixture("b", address=5),  # 1+9=10 overlaps with 5
    ]
    r = client.put("/api/mock/rigs/conflict_test", json={"fixtures": bad_fixtures})
    assert r.status_code == 200  # save succeeded
    body = r.json()
    assert len(body["conflicts"]) > 0
    # Conflict description should name both fixtures.
    descriptions = " ".join(c["description"] for c in body["conflicts"])
    assert "a" in descriptions and "b" in descriptions


# ---------------------------------------------------------------------------
# Validation (Cycle-1 panel H1, A13)


def test_put_rejects_invalid_name_with_400_invalid_rig_name(client):
    r = client.put("/api/mock/rigs/_active", json={"fixtures": [_laser_fixture()]})
    assert r.status_code == 400
    body = r.json()
    assert body["detail"]["detail"] == "invalid_rig_name"


def test_put_rejects_enabled_laser_with_null_profile_with_400(client):
    """Cycle-1 panel Kilo A13: enabled lasers MUST have a profile."""
    bad = _laser_fixture("laser-bad", profile=None, enabled=True)
    r = client.put("/api/mock/rigs/bad_rig", json={"fixtures": [bad]})
    assert r.status_code == 400
    body = r.json()
    assert body["detail"]["detail"] == "type_profile_required"


def test_put_rejects_duplicate_fixture_ids_with_400(client):
    fixtures = [_laser_fixture("dup"), _laser_fixture("dup", address=20)]
    r = client.put("/api/mock/rigs/dup_rig", json={"fixtures": fixtures})
    assert r.status_code == 400
    body = r.json()
    assert body["detail"]["detail"] == "duplicate_fixture_id"


def test_get_404_for_missing_rig(client):
    r = client.get("/api/mock/rigs/never_existed")
    assert r.status_code == 404


def test_get_400_for_invalid_name(client):
    r = client.get("/api/mock/rigs/_active")
    assert r.status_code == 400
    body = r.json()
    assert body["detail"]["detail"] == "invalid_rig_name"


# ---------------------------------------------------------------------------
# Schema-newer-than-build (closes Codex H#5)


def test_get_returns_422_for_rig_with_newer_schema(client):
    fixtures = [_laser_fixture()]
    client.put("/api/mock/rigs/futuristic", json={"fixtures": fixtures})
    # Manually bump the schema version on disk.
    path = rig_storage.rig_path("futuristic")
    payload = json.loads(path.read_text())
    payload[rig_storage._SCHEMA_KEY] = 99
    path.write_text(json.dumps(payload), encoding="utf-8")
    r = client.get("/api/mock/rigs/futuristic")
    assert r.status_code == 422
    assert r.json()["detail"]["detail"] == "schema_too_new"


# ---------------------------------------------------------------------------
# Startup hydration from active rig (Cycle-1 panel C1)


def test_create_app_hydrates_canvas_from_active_rig(fixtures_dir):
    """Cycle-1 panel Phase A startup wiring: when an active rig
    exists, the new MockRigStore boots from it instead of defaults."""
    fixtures = [_laser_fixture("hydrated-1"), _laser_fixture("hydrated-2", address=40)]
    rig_storage.save_rig("morning_setup", fixtures)
    rig_storage.set_active_rig("morning_setup")
    app = create_app(fixtures_dir=fixtures_dir)
    client = TestClient(app)
    state = client.get("/api/mock/state").json()
    assert {f["id"] for f in state["fixtures"]} == {"hydrated-1", "hydrated-2"}


def test_create_app_falls_back_to_defaults_when_active_rig_missing(fixtures_dir, tmp_path):
    """Cycle-1 panel C1 (3/4 convergent): a stale active pointer MUST
    NOT crash app construction. The auto-clear fires inside
    `get_active_rig_name`, so create_app sees no active rig."""
    fixtures = [_laser_fixture("doomed-a")]
    rig_storage.save_rig("doomed", fixtures)
    rig_storage.set_active_rig("doomed")
    rig_storage.rig_path("doomed").unlink()  # out-of-band delete
    # Must not raise.
    app = create_app(fixtures_dir=fixtures_dir)
    client = TestClient(app)
    # Default rig fixtures, not the deleted one.
    state = client.get("/api/mock/state").json()
    assert "doomed-a" not in {f["id"] for f in state["fixtures"]}
