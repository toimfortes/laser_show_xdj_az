"""Pinning tests for the Phase B runtime bridge (`cli._apply_active_rig_to_settings`).

The bridge overlays a saved rig onto `Settings.fixtures` at CLI startup
so the actual graph reflects the user's patch instead of YAML defaults.
Each test pins one Cycle-1 panel finding so a future refactor cannot
silently re-introduce the defect.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml

from photonic_synesthesia.core.config import Settings
from photonic_synesthesia.platform import rig_storage
from photonic_synesthesia.platform.rig_storage import (
    Conflict,
    RigBridgeError,
    detect_address_conflicts,
    materialize_to_fixture_configs,
    save_rig,
    set_active_rig,
)
from photonic_synesthesia.ui.cli import _apply_active_rig_to_settings


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
    # Hybrid profile — closes Kilo H6.
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


def _laser_fixture(fid="laser-1", *, address=1, profile="laser_generic_9ch", enabled=True, type_="laser"):
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
        "universe": 1,
        "address": address,
        "profile": profile,
        "enabled": enabled,
    }


def _settings(fixtures_dir):
    s = Settings()
    s.fixtures_dir = fixtures_dir
    return s


def _ctx(*, config_path=None):
    """Build a minimal Click-context-like object for the bridge."""
    return SimpleNamespace(obj={"config_path": config_path})


# ---------------------------------------------------------------------------
# Materialization filter rules


def test_materialize_skips_fixtures_with_null_profile(fixtures_dir):
    """Cycle-1 panel C2 + Gemini H1: null-profile fixtures are skipped
    silently (visual-only). They were filtered BEFORE FixtureConfig
    construction so pydantic ValidationError never fires."""
    rig = {
        "name": "test",
        "fixtures": [
            _laser_fixture("vis-1", profile=None, enabled=False, type_="wash"),
            _laser_fixture("good", address=20, profile="laser_generic_9ch"),
        ],
    }
    configs, _ = materialize_to_fixture_configs(rig, fixtures_dir)
    assert [c.id for c in configs] == ["good"]


def test_materialize_skips_fixture_with_missing_profile_yaml_and_warns(fixtures_dir):
    """Cycle-1 panel H3 (3/4 convergent): missing profile YAML MUST
    surface a warning, NOT crash startup."""
    rig = {
        "name": "test",
        "fixtures": [
            _laser_fixture("good"),
            _laser_fixture("bad", address=30, profile="never_existed"),
        ],
    }
    configs, warnings = materialize_to_fixture_configs(rig, fixtures_dir)
    assert [c.id for c in configs] == ["good"]
    assert any("never_existed" in w and "missing" in w for w in warnings)


def test_materialize_skips_fixture_with_corrupt_profile_yaml_and_warns(fixtures_dir):
    """Corrupt YAML files are tolerated by `_read_profile_channels`
    (returns None), so conflict detection silently skips them.
    Materialization itself succeeds since the file exists."""
    (fixtures_dir / "broken.yaml").write_text("not: [valid: yaml", encoding="utf-8")
    rig = {
        "name": "test",
        "fixtures": [
            _laser_fixture("a", profile="broken"),
            _laser_fixture("b", address=20, profile="broken"),
        ],
    }
    # Should not raise (no detectable conflict due to unreadable channel count).
    configs, warnings = materialize_to_fixture_configs(rig, fixtures_dir)
    assert len(configs) == 2


def test_materialize_dereferences_dmx_adapter_profile_chain(fixtures_dir):
    """Cycle-1 panel Kilo H6: laser_aucd_cx338b_hybrid has no top-level
    `channels` field; conflict detection MUST follow `dmx_adapter_profile`
    or the conflict is silently missed."""
    rig = {
        "name": "test",
        "fixtures": [
            _laser_fixture("a", address=1, profile="laser_aucd_cx338b_hybrid"),
            _laser_fixture("b", address=5, profile="laser_aucd_cx338b_hybrid"),
        ],
    }
    with pytest.raises(RigBridgeError, match="DMX address conflict"):
        materialize_to_fixture_configs(rig, fixtures_dir)


def test_materialize_does_not_construct_fixtureconfig_with_null_profile(fixtures_dir):
    """Cycle-1 panel C2 (Kilo CRITICAL): null filter must happen BEFORE
    FixtureConfig construction. If construction were attempted with
    `profile=None`, pydantic would raise ValidationError and crash
    startup. This test proves construction is never attempted."""
    rig = {
        "name": "test",
        "fixtures": [
            _laser_fixture("null-prof", profile=None, enabled=False),
            _laser_fixture("good", profile="laser_generic_9ch"),
        ],
    }
    # No exception means C2 is closed — null was filtered.
    configs, _ = materialize_to_fixture_configs(rig, fixtures_dir)
    assert [c.id for c in configs] == ["good"]


# ---------------------------------------------------------------------------
# CLI bridge precedence (closes Kilo C3)


def test_active_rig_overrides_default_settings_fixtures_when_no_config_flag(fixtures_dir):
    """When no --config flag is passed AND an active rig exists, the
    bridge MUST replace `settings.fixtures` with the materialized list."""
    fixtures = [_laser_fixture("a"), _laser_fixture("b", address=20)]
    save_rig("antonios_lights", fixtures)
    set_active_rig("antonios_lights")
    settings = _settings(fixtures_dir)
    settings.fixtures = []  # default
    _apply_active_rig_to_settings(_ctx(config_path=None), settings)
    assert {f.id for f in settings.fixtures} == {"a", "b"}


def test_config_path_takes_precedence_over_active_rig(fixtures_dir, tmp_path):
    """Cycle-1 panel C3 (Kilo CRITICAL): MUST use `ctx.obj['config_path']`
    NOT `ctx.get_parameter_source('config')` (which is on the parent
    cli group). When `config_path` is truthy, the active rig is skipped
    even if one exists, and `settings.fixtures` is preserved as-is."""
    fixtures = [_laser_fixture("active-a")]
    save_rig("active_rig", fixtures)
    set_active_rig("active_rig")
    settings = _settings(fixtures_dir)
    yaml_fixtures = settings.fixtures = []  # simulate YAML-loaded settings
    config_path = tmp_path / "fake.yaml"
    config_path.touch()
    _apply_active_rig_to_settings(_ctx(config_path=config_path), settings)
    # Active rig was IGNORED because --config was passed.
    assert settings.fixtures == yaml_fixtures


def test_no_active_rig_leaves_settings_fixtures_untouched(fixtures_dir):
    """Default state (no _active.json): bridge is a no-op."""
    settings = _settings(fixtures_dir)
    settings.fixtures = ["sentinel"]  # type: ignore[list-item]
    _apply_active_rig_to_settings(_ctx(config_path=None), settings)
    assert settings.fixtures == ["sentinel"]


# ---------------------------------------------------------------------------
# Failure recovery (closes C1, Gemini C1, Claude H1)


def test_active_rig_load_failure_falls_back_to_defaults_with_clean_message(
    fixtures_dir, capsys
):
    """Cycle-1 panel C1: stale active pointer or corrupt rig MUST NOT
    crash startup. The bridge degrades to a warning + leaves
    `settings.fixtures` at its prior value (the YAML defaults)."""
    fixtures = [_laser_fixture("doomed-a")]
    save_rig("doomed", fixtures)
    set_active_rig("doomed")
    # Out-of-band: corrupt the rig file (file exists but parses incorrectly).
    rig_storage.rig_path("doomed").write_text("not valid json", encoding="utf-8")
    settings = _settings(fixtures_dir)
    yaml_fixtures = settings.fixtures = ["sentinel-yaml-fixture"]  # type: ignore[list-item]
    # MUST NOT raise.
    _apply_active_rig_to_settings(_ctx(config_path=None), settings)
    captured = capsys.readouterr()
    assert "could not be loaded" in captured.err
    assert "Falling back to default" in captured.err
    assert settings.fixtures == yaml_fixtures


def test_stale_active_pointer_silently_returns_no_op(fixtures_dir, capsys):
    """If `_active.json` points to a deleted rig file, get_active_rig_name
    auto-clears and returns None; the bridge sees no active rig and is
    a clean no-op (no warning text — the auto-clear log is all we get)."""
    save_rig("doomed", [_laser_fixture()])
    set_active_rig("doomed")
    rig_storage.rig_path("doomed").unlink()
    settings = _settings(fixtures_dir)
    settings.fixtures = ["sentinel"]  # type: ignore[list-item]
    _apply_active_rig_to_settings(_ctx(config_path=None), settings)
    assert settings.fixtures == ["sentinel"]


# ---------------------------------------------------------------------------
# Empty-materialize policy (closes H4 — Gemini + Claude + Kilo)


def test_rig_with_fixtures_but_zero_runtime_capable_emits_empty_settings_with_warning(
    fixtures_dir, capsys
):
    """Cycle-1 panel H4: a rig that has fixtures (e.g. a wash-only
    canvas) but ZERO runtime-capable (laser+profile) ones MUST set
    `settings.fixtures = []` AND warn — not silently retain YAML
    defaults. The user explicitly chose this rig; respect it."""
    visual_only = [
        _laser_fixture("wash-1", profile=None, enabled=False, type_="wash"),
        _laser_fixture("mover-1", profile=None, enabled=False, type_="moving_head"),
    ]
    save_rig("visual_only_rig", visual_only)
    set_active_rig("visual_only_rig")
    settings = _settings(fixtures_dir)
    settings.fixtures = ["yaml-default"]  # type: ignore[list-item]
    _apply_active_rig_to_settings(_ctx(config_path=None), settings)
    captured = capsys.readouterr()
    assert "ZERO are runtime-capable" in captured.err
    assert settings.fixtures == []  # explicit empty, not YAML defaults


def test_rig_with_no_fixtures_at_all_does_not_warn(fixtures_dir, capsys):
    """A truly empty rig (no fixtures of any kind) is also acceptable;
    the bridge sets settings.fixtures = [] but doesn't emit the
    'ZERO are runtime-capable' warning since there's nothing TO be
    capable."""
    save_rig("empty_rig", [])
    set_active_rig("empty_rig")
    settings = _settings(fixtures_dir)
    settings.fixtures = []
    _apply_active_rig_to_settings(_ctx(config_path=None), settings)
    captured = capsys.readouterr()
    assert "ZERO are runtime-capable" not in captured.err


# ---------------------------------------------------------------------------
# Error messages (closes Codex M2)


def test_address_conflict_surfaces_user_friendly_message(fixtures_dir, capsys):
    """RigBridgeError text MUST name BOTH conflicting fixtures so the
    user can fix the conflict in the UI."""
    fixtures = [_laser_fixture("conflict-a", address=1), _laser_fixture("conflict-b", address=5)]
    save_rig("conflicting", fixtures)
    set_active_rig("conflicting")
    settings = _settings(fixtures_dir)
    settings.fixtures = ["yaml-default"]  # type: ignore[list-item]
    # Bridge degrades gracefully; user sees the conflict description in stderr.
    _apply_active_rig_to_settings(_ctx(config_path=None), settings)
    captured = capsys.readouterr()
    assert "conflict-a" in captured.err
    assert "conflict-b" in captured.err
    assert "could not be loaded" in captured.err
    # Settings.fixtures preserved (fall back to YAML).
    assert settings.fixtures == ["yaml-default"]


# ---------------------------------------------------------------------------
# detect_address_conflicts edge cases (closes Codex M3 + dir-missing)


def test_detect_address_conflicts_handles_missing_profiles_dir_returns_empty(tmp_path):
    """Total function: never raises even if profiles_dir is absent."""
    fixtures = [_laser_fixture("a"), _laser_fixture("b", address=20)]
    assert detect_address_conflicts(fixtures, tmp_path / "missing") == []


def test_detect_address_conflicts_describe_method_includes_both_ids(fixtures_dir):
    fixtures = [_laser_fixture("aa", address=1), _laser_fixture("bb", address=3)]
    conflicts = detect_address_conflicts(fixtures, fixtures_dir)
    assert len(conflicts) > 0
    description = conflicts[0].describe()
    assert "aa" in description and "bb" in description


# ---------------------------------------------------------------------------
# Sanity: bridge has no effect when ctx.obj is None (defensive)


def test_bridge_handles_missing_ctx_obj_gracefully(fixtures_dir):
    """If ctx.obj is None (test harness not setting it up), the bridge
    treats it as 'no config_path' which is the safe default."""
    fixtures = [_laser_fixture("a")]
    save_rig("test_rig", fixtures)
    set_active_rig("test_rig")
    settings = _settings(fixtures_dir)
    settings.fixtures = []
    ctx = SimpleNamespace(obj=None)
    _apply_active_rig_to_settings(ctx, settings)  # must not raise
    assert {f.id for f in settings.fixtures} == {"a"}
