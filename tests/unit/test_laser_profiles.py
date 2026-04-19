from __future__ import annotations

from pathlib import Path

from photonic_synesthesia.core.config import FixtureConfig
from photonic_synesthesia.laser import resolve_laser_profile


def test_resolve_cx338b_hybrid_profile_exposes_manual_capabilities() -> None:
    fixture = FixtureConfig(
        id="laser-main",
        name="Main Festival Laser",
        type="laser",
        profile="laser_aucd_cx338b_hybrid",
        start_address=1,
        enabled=True,
    )

    profile = resolve_laser_profile(fixture, Path("config/fixtures"))

    assert profile.control_surface == "ilda"
    assert profile.fallback_surface == "dmx_adapter"
    assert profile.adapter_assumption is True
    assert profile.dmx_channel_count == 9
    assert profile.channel_map["x_roll"] == 4
    assert profile.channel_map["z_roll"] == 6
    assert profile.capabilities["app_name"] == "Light Elf"
    assert 20 in profile.capabilities["dmx_modes"]
    assert "animation" in profile.capabilities["app_functions"]
    assert "rotation" in profile.capabilities["adjustable_parameters"]
    assert "db25" in profile.connections["ilda"]
    assert profile.specifications["scan_speed_kpps"] == 25
    assert profile.specifications["laser_sources"]["blue"] == "450nm@3.5W"
    assert profile.safety["audience_scanning_allowed"] is False
    assert profile.metadata["manual_source"] == "https://manuals.plus/asin/B0F9TFPHLF"


def test_resolve_missing_laser_profile_falls_back_to_generic_defaults() -> None:
    fixture = FixtureConfig(
        id="laser-test",
        name="Fallback Laser",
        type="laser",
        profile="missing_profile",
        start_address=1,
        enabled=True,
    )

    profile = resolve_laser_profile(fixture, Path("config/fixtures"))

    assert profile.control_surface == "dmx"
    assert profile.dmx_channel_count == 7
    assert profile.channel_map["zoom"] == 6
    assert profile.connections == {}
    assert profile.specifications == {}
