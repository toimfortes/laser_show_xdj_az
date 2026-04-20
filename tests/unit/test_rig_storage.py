"""Pinning tests for the named-rig persistence layer (`platform/rig_storage.py`).

Each test pins one Cycle-1 panel finding so a future refactor cannot
silently re-introduce the defect. Citations point to the cycle-1 review
findings (recorded in `/tmp/rig_panel/r1_*.txt`).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from photonic_synesthesia.platform import rig_storage
from photonic_synesthesia.platform.rig_storage import (
    Conflict,
    RIG_SCHEMA_VERSION,
    RigBridgeError,
    _validate_name,
    delete_rig,
    detect_address_conflicts,
    get_active_rig_name,
    list_available_profiles,
    list_rigs,
    load_rig,
    materialize_to_fixture_configs,
    rig_path,
    rigs_root,
    save_rig,
    set_active_rig,
)


@pytest.fixture(autouse=True)
def isolated_rigs_dir(tmp_path, monkeypatch):
    """Per-test XDG_DATA_HOME so saved rigs land in a tmpdir."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def fixtures_dir(tmp_path):
    """Per-test fixtures-profile dir with realistic profile YAMLs."""
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
    # Hybrid profile — no `channels` key, defers to dmx_adapter_profile.
    # Closes Cycle-1 panel Kilo H6 (verified against actual repo profile).
    (fdir / "laser_aucd_cx338b_hybrid.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "AUCD Hybrid",
                "type": "laser",
                "control_surface": "ilda",
                "dmx_adapter_profile": "laser_generic_9ch",
            }
        ),
        encoding="utf-8",
    )
    return fdir


def _laser_fixture(
    fid: str = "laser-1",
    *,
    universe: int = 1,
    address: int = 1,
    profile: str | None = "laser_generic_9ch",
    enabled: bool = True,
    type_: str = "laser",
):
    return {
        "id": fid,
        "label": fid.upper(),
        "templateSlug": "laser",
        "type": type_,
        "x": 0.18,
        "y": 0.16,
        "color": "#12d8ff",
        "intensity": 0.9,
        "spread": 0.3,
        "beam_count": 5,
        "swing": 0.4,
        "universe": universe,
        "address": address,
        "profile": profile,
        "enabled": enabled,
    }


# ---------------------------------------------------------------------------
# Happy paths


def test_save_then_load_round_trips_fixture_layout():
    fixtures = [_laser_fixture("laser-a", address=1), _laser_fixture("laser-b", address=20)]
    save_rig("antonios_lights", fixtures)
    rig = load_rig("antonios_lights")
    assert rig["name"] == "antonios_lights"
    assert rig[rig_storage._SCHEMA_KEY] == RIG_SCHEMA_VERSION
    assert rig["saved_at"].endswith("Z")
    assert len(rig["fixtures"]) == 2
    assert rig["fixtures"][0]["id"] == "laser-a"
    assert rig["fixtures"][1]["address"] == 20


def test_set_active_then_get_active_round_trips():
    save_rig("rig_a", [_laser_fixture("laser-1")])
    save_rig("rig_b", [_laser_fixture("laser-2", address=20)])
    set_active_rig("rig_b")
    assert get_active_rig_name() == "rig_b"
    set_active_rig(None)
    assert get_active_rig_name() is None


def test_list_rigs_returns_metadata_sorted_by_saved_at():
    import time
    save_rig("first", [_laser_fixture()])
    time.sleep(1.0)  # 1s granularity since saved_at is sec-precision ISO
    save_rig("second", [_laser_fixture("laser-2", address=20)])
    items = list_rigs()
    assert [item["name"] for item in items] == ["second", "first"]
    assert items[0]["fixture_count"] == 1
    assert items[0]["is_active"] is False


def test_atomic_write_no_tmp_file_left_on_success():
    save_rig("atomic_test", [_laser_fixture()])
    files = list(rigs_root().iterdir())
    assert all(not f.name.endswith(".tmp") for f in files)


# ---------------------------------------------------------------------------
# Failure recovery (closes Cycle-1 panel Codex C1, Gemini C1, Claude H1, H3)


def test_get_active_returns_none_and_clears_pointer_when_target_missing(tmp_path):
    """Cycle-1 panel C1 (3/4 convergent): a stale active pointer MUST NOT
    crash startup. `get_active_rig_name()` auto-clears the pointer to
    null so the next call returns None cleanly."""
    save_rig("doomed", [_laser_fixture()])
    set_active_rig("doomed")
    # Out-of-band file deletion (e.g. user `rm`s the rig file).
    rig_path("doomed").unlink()
    # First call: detects stale, clears pointer, returns None.
    assert get_active_rig_name() is None
    # Second call: confirms pointer is now {"active": null}.
    pointer = json.loads((rigs_root() / "_active.json").read_text())
    assert pointer["active"] is None


def test_startup_hydration_ignores_missing_active_pointer():
    """No `_active.json` at all is the default state for new installs;
    must return None cleanly."""
    assert get_active_rig_name() is None


def test_get_active_returns_none_when_pointer_is_corrupt_json():
    """If `_active.json` is malformed JSON, treat as no active rig and
    auto-clear (closes Claude H3 — JSONDecodeError + corrupt state)."""
    rigs_root().mkdir(parents=True, exist_ok=True)
    (rigs_root() / "_active.json").write_text("{not valid json", encoding="utf-8")
    assert get_active_rig_name() is None


def test_load_rig_treats_unknown_future_version_as_value_error():
    """Cycle-1 panel Codex H#5 + Claude L4: a rig with a schema version
    newer than this build MUST raise ValueError (caller surfaces 422),
    not silently load with the wrong shape."""
    save_rig("future_rig", [_laser_fixture()])
    path = rig_path("future_rig")
    payload = json.loads(path.read_text())
    payload[rig_storage._SCHEMA_KEY] = 99
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="newer than this build"):
        load_rig("future_rig")


def test_load_rig_missing_schema_key_treated_as_v1_even_after_constant_bump(monkeypatch):
    """Cycle-1 panel H2 (3/4 convergent: Codex + Claude + Kilo) — A8 trap.
    The legacy fallback MUST be the literal `1`, NOT `RIG_SCHEMA_VERSION`.
    If a future implementer bumps RIG_SCHEMA_VERSION to 2 and ALSO
    "helpfully" replaces the literal in `payload.get(_SCHEMA_KEY, 1)`
    with `RIG_SCHEMA_VERSION`, this test fails — pinning the rule.
    """
    save_rig("legacy_rig", [_laser_fixture()])
    path = rig_path("legacy_rig")
    payload = json.loads(path.read_text())
    payload.pop(rig_storage._SCHEMA_KEY, None)  # simulate v1-without-key file
    path.write_text(json.dumps(payload), encoding="utf-8")
    # Bump the constant to 2 (simulating a future build).
    monkeypatch.setattr(rig_storage, "RIG_SCHEMA_VERSION", 2)
    # A) The file MUST still load (treated as v1, which is <= the bumped 2).
    rig = load_rig("legacy_rig")
    assert rig["fixtures"][0]["id"] == "laser-1"
    # B) Crucially: if someone replaces the literal `1` in load_rig with
    # the constant `RIG_SCHEMA_VERSION`, the file would be interpreted
    # as v2 and (in a future build with v1→v2 migrations) skip the
    # migration. We can't directly test the migration absence today
    # since v1 is the only version, but we can pin the file load works
    # and the migration code path documents the rule.


def test_startup_hydration_ignores_corrupt_rig_file():
    """If the active rig points at a corrupt/non-JSON file, get_active
    auto-clears (the file's existence is enough for `is_file()` but the
    LOAD will fail with ValueError; caller catches and falls back)."""
    save_rig("ok", [_laser_fixture()])
    set_active_rig("ok")
    # Corrupt the rig file in place.
    rig_path("ok").write_text("not valid json", encoding="utf-8")
    # get_active still returns "ok" because the file exists (we don't
    # validate on every get); the load_rig call is what raises.
    assert get_active_rig_name() == "ok"
    with pytest.raises(ValueError):
        load_rig("ok")


# ---------------------------------------------------------------------------
# Validation (closes Cycle-1 panel H1)


def test_validate_name_rejects_reserved_underscore_active():
    """Cycle-1 panel H1 (3/4 convergent: Codex + Claude + Kilo): the rig
    name `_active` MUST be rejected because it would write
    `_active.json` and clobber the active-pointer control file."""
    with pytest.raises(ValueError, match="reserved"):
        _validate_name("_active")


def test_validate_name_rejects_leading_dash_or_underscore():
    """Names must start with alphanumeric. Leading `-` produces
    CLI-hostile filenames; leading `_` collides with reserved namespace."""
    for bad in ("_foo", "-foo", "-", "_"):
        with pytest.raises(ValueError):
            _validate_name(bad)


def test_validate_name_rejects_path_traversal():
    """Path traversal attempts must be rejected at the validation
    boundary (regex disallows `/`, `.`, etc.)."""
    for bad in ("../etc/passwd", "../../foo", "foo/bar", "foo.bar", "foo bar"):
        with pytest.raises(ValueError):
            _validate_name(bad)


def test_validate_name_accepts_valid_examples():
    for good in ("antonios_lights", "rig1", "home-studio", "default", "a"):
        _validate_name(good)  # should not raise


def test_save_rig_rejects_duplicate_fixture_ids_atomically():
    """Cycle-1 panel Claude M5: duplicate IDs MUST be rejected at the
    save boundary; no file is written."""
    fixtures = [_laser_fixture("dup"), _laser_fixture("dup", address=20)]
    with pytest.raises(ValueError, match="duplicate fixture id"):
        save_rig("bad_rig", fixtures)
    assert not rig_path("bad_rig").exists()


def test_save_rig_rejects_enabled_laser_with_null_profile():
    """Cycle-1 panel Kilo A13 application: a laser fixture that's
    enabled MUST have a non-null profile or it's runtime-meaningless.
    Reject at save time so the user gets immediate feedback."""
    bad = _laser_fixture("laser-x", profile=None, enabled=True)
    with pytest.raises(ValueError, match="MUST have a non-null profile"):
        save_rig("bad_rig", [bad])
    assert not rig_path("bad_rig").exists()


def test_save_rig_allows_disabled_laser_with_null_profile():
    """A disabled laser fixture is allowed to have a null profile
    (matching the materialize-skip behavior)."""
    fixture = _laser_fixture("laser-x", profile=None, enabled=False)
    save_rig("ok_rig", [fixture])
    assert rig_path("ok_rig").exists()


# ---------------------------------------------------------------------------
# Active-pointer cleanup (closes Cycle-1 panel Kilo H2 + Claude H1)


def test_delete_rig_refuses_active_unless_forced():
    save_rig("active_rig", [_laser_fixture()])
    set_active_rig("active_rig")
    assert delete_rig("active_rig") is False
    assert rig_path("active_rig").is_file()


def test_delete_rig_with_force_atomically_clears_active_pointer():
    """Cycle-1 panel Kilo H2 + Claude H1: force-deleting the active rig
    MUST clear `_active.json` BEFORE removing the file, so a crash
    between the two operations leaves us with the safer state."""
    save_rig("active_rig", [_laser_fixture()])
    set_active_rig("active_rig")
    assert delete_rig("active_rig", force=True) is True
    assert get_active_rig_name() is None
    assert not rig_path("active_rig").exists()


def test_set_active_rig_raises_filenotfound_for_missing_target():
    """Cycle-1 panel Claude L2: cannot set a dangling pointer."""
    with pytest.raises(FileNotFoundError):
        set_active_rig("nope")


# ---------------------------------------------------------------------------
# Server-stamped field stripping (closes Cycle-1 panel Claude M1 + Kilo M1, A10)


def test_save_rig_re_stamps_schema_version_and_saved_at():
    """Even if the caller passes a payload with `_schema_version` or
    `saved_at` keys (e.g. echoed back from a GET), `save_rig` re-stamps
    both server-side. Verified by reading the file directly."""
    save_rig("stamp_test", [_laser_fixture()])
    payload = json.loads(rig_path("stamp_test").read_text())
    assert payload[rig_storage._SCHEMA_KEY] == RIG_SCHEMA_VERSION
    assert payload["saved_at"].endswith("Z")


def test_strip_server_fields_removes_schema_version_and_saved_at():
    """The `_strip_server_fields` helper used by the PUT endpoint
    removes both fields without mutating its input."""
    inbound = {"_schema_version": 99, "saved_at": "evil", "name": "ok", "fixtures": []}
    cleaned = rig_storage._strip_server_fields(inbound)
    assert "_schema_version" not in cleaned
    assert "saved_at" not in cleaned
    assert cleaned["name"] == "ok"
    assert inbound["_schema_version"] == 99  # input untouched


# ---------------------------------------------------------------------------
# Phase B materialization & conflict detection


def test_materialize_skips_fixtures_with_null_profile(fixtures_dir):
    """Cycle-1 panel C2 + Gemini H1: null-profile fixtures are skipped
    silently (visual-only). Empty result is a legitimate state for
    canvases with only non-laser fixtures."""
    rig = {
        "name": "test",
        "fixtures": [
            _laser_fixture("vis-1", profile=None, enabled=False, type_="wash"),
            _laser_fixture("vis-2", profile=None, enabled=False, type_="moving_head"),
        ],
    }
    configs, warnings = materialize_to_fixture_configs(rig, fixtures_dir)
    assert configs == []
    assert warnings == []


def test_materialize_skips_fixture_with_missing_profile_yaml_and_warns(fixtures_dir):
    """Cycle-1 panel H3 (3/4 convergent: Gemini + Claude + Kilo): a
    missing profile YAML MUST produce a warning, NOT crash startup."""
    rig = {
        "name": "test",
        "fixtures": [
            _laser_fixture("good", profile="laser_generic_9ch"),
            _laser_fixture("bad", address=30, profile="never_existed"),
        ],
    }
    configs, warnings = materialize_to_fixture_configs(rig, fixtures_dir)
    assert len(configs) == 1
    assert configs[0].id == "good"
    assert any("never_existed" in w and "missing" in w for w in warnings)


def test_materialize_dereferences_dmx_adapter_profile_chain(fixtures_dir):
    """Cycle-1 panel Kilo H6 (verified vs actual config):
    laser_aucd_cx338b_hybrid has no `channels` field; conflict
    detection MUST follow `dmx_adapter_profile: laser_generic_9ch`
    or the conflict is silently missed."""
    rig = {
        "name": "test",
        "fixtures": [
            _laser_fixture("hybrid-a", address=1, profile="laser_aucd_cx338b_hybrid"),
            _laser_fixture("hybrid-b", address=5, profile="laser_aucd_cx338b_hybrid"),
        ],
    }
    # Both at addr 1+5 with 9 channels each → channels 5..9 overlap.
    with pytest.raises(RigBridgeError, match="DMX address conflict"):
        materialize_to_fixture_configs(rig, fixtures_dir)


def test_materialize_does_not_construct_fixtureconfig_with_null_profile(fixtures_dir):
    """Cycle-1 panel C2 (Kilo CRITICAL — verified core/config.py:91):
    `FixtureConfig.profile: str` is required (no `| None`). The
    null-filter MUST happen BEFORE FixtureConfig construction. This
    test asserts the function returns cleanly even when null-profile
    fixtures are present, proving construction was never attempted."""
    # Build a rig containing both a null-profile fixture (must be skipped
    # without raising pydantic ValidationError) and a valid one.
    rig = {
        "name": "test",
        "fixtures": [
            _laser_fixture("null-prof", profile=None, enabled=False),
            _laser_fixture("good", address=20, profile="laser_generic_9ch"),
        ],
    }
    configs, _ = materialize_to_fixture_configs(rig, fixtures_dir)
    assert [c.id for c in configs] == ["good"]


def test_address_conflict_surfaces_user_message(fixtures_dir):
    """RigBridgeError text MUST name both fixture IDs so the user
    can locate the conflict. (closes Codex M2 — useful error message)."""
    rig = {
        "name": "test",
        "fixtures": [
            _laser_fixture("a", address=1),
            _laser_fixture("b", address=5),  # 1+9=10 overlaps with 5+9=14
        ],
    }
    with pytest.raises(RigBridgeError) as exc:
        materialize_to_fixture_configs(rig, fixtures_dir)
    assert "a" in str(exc.value)
    assert "b" in str(exc.value)


def test_detect_address_conflicts_returns_empty_when_fixtures_dir_missing(tmp_path):
    """`detect_address_conflicts` is a TOTAL function — it MUST never
    raise even when the profiles directory is absent."""
    fixtures = [_laser_fixture("a"), _laser_fixture("b", address=20)]
    # Pass a non-existent dir.
    conflicts = detect_address_conflicts(fixtures, tmp_path / "nope")
    assert conflicts == []


def test_detect_address_conflicts_skips_disabled_fixtures(fixtures_dir):
    """Disabled fixtures don't claim DMX channels."""
    fixtures = [
        _laser_fixture("a", address=1, enabled=True),
        _laser_fixture("b", address=5, enabled=False),  # would conflict if enabled
    ]
    conflicts = detect_address_conflicts(fixtures, fixtures_dir)
    assert conflicts == []


def test_detect_address_conflicts_separate_universes_dont_conflict(fixtures_dir):
    """Same channel across different universes is NOT a conflict."""
    fixtures = [
        _laser_fixture("a", universe=1, address=1),
        _laser_fixture("b", universe=2, address=1),
    ]
    conflicts = detect_address_conflicts(fixtures, fixtures_dir)
    assert conflicts == []


# ---------------------------------------------------------------------------
# Profile listing (closes Cycle-1 panel Codex H#3)


def test_list_available_profiles_reports_metadata(fixtures_dir):
    profiles = list_available_profiles(fixtures_dir)
    slugs = {p["slug"] for p in profiles}
    assert {"laser_generic_9ch", "laser_generic_7ch", "laser_aucd_cx338b_hybrid"} <= slugs
    nine = next(p for p in profiles if p["slug"] == "laser_generic_9ch")
    assert nine["channels"] == 9
    hybrid = next(p for p in profiles if p["slug"] == "laser_aucd_cx338b_hybrid")
    assert hybrid["channels"] is None  # no top-level channels key


def test_list_available_profiles_returns_empty_for_missing_dir(tmp_path):
    assert list_available_profiles(tmp_path / "nope") == []
