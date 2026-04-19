"""Laser profile resolution for hybrid ILDA/DMX fixtures."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from photonic_synesthesia.core.config import FixtureConfig, load_fixture_profile

_CHANNEL_ROLE_ALIASES = {
    "mode": "mode",
    "pattern": "pattern",
    "x_position": "x_pos",
    "x_pos": "x_pos",
    "y_position": "y_pos",
    "y_pos": "y_pos",
    "scan_speed": "scan_speed",
    "pattern_play_speed": "pattern_speed",
    "pattern_speed": "pattern_speed",
    "zoom": "zoom",
    "x_roll": "x_roll",
    "y_roll": "y_roll",
    "z_roll": "z_roll",
    "rotation": "z_roll",
    "strobe": "strobe",
    "color": "color",
}

_DEFAULT_CHANNEL_MAP = {
    "mode": 0,
    "pattern": 1,
    "x_pos": 2,
    "y_pos": 3,
    "scan_speed": 4,
    "pattern_speed": 5,
    "zoom": 6,
}


@dataclass(frozen=True)
class LaserFixtureProfile:
    """Resolved laser fixture profile, including hybrid control metadata."""

    fixture_id: str
    profile_name: str
    control_surface: str = "dmx"
    fallback_surface: str | None = None
    dmx_channel_count: int = 7
    channel_map: dict[str, int] = field(default_factory=lambda: dict(_DEFAULT_CHANNEL_MAP))
    capabilities: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    connections: dict[str, Any] = field(default_factory=dict)
    specifications: dict[str, Any] = field(default_factory=dict)
    safety: dict[str, Any] = field(default_factory=dict)
    adapter_assumption: bool = False


def _merge_profile(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def _role_map_from_profile(profile: dict[str, Any]) -> dict[str, int]:
    channel_map = dict(_DEFAULT_CHANNEL_MAP)
    raw_map = profile.get("channel_map", {})
    for raw_index, channel_info in raw_map.items():
        if not isinstance(channel_info, dict):
            continue
        name = str(channel_info.get("name", "")).strip().lower()
        role = _CHANNEL_ROLE_ALIASES.get(name)
        if role is None:
            continue
        channel_number = int(raw_index) - 1
        channel_map[role] = max(0, channel_number)
    return channel_map


def resolve_laser_profile(fixture: FixtureConfig, fixtures_dir: Path) -> LaserFixtureProfile:
    """Resolve a laser fixture profile, supporting DMX adapter inheritance."""
    default_profile = LaserFixtureProfile(
        fixture_id=fixture.id,
        profile_name=fixture.profile,
    )
    if fixture.type != "laser":
        return default_profile

    profile_path = fixtures_dir / f"{fixture.profile}.yaml"
    if not profile_path.exists():
        return default_profile

    profile = load_fixture_profile(profile_path)
    adapter_profile_name = profile.get("dmx_adapter_profile")
    if isinstance(adapter_profile_name, str):
        adapter_path = fixtures_dir / f"{adapter_profile_name}.yaml"
        if adapter_path.exists():
            adapter_profile = load_fixture_profile(adapter_path)
            profile = _merge_profile(adapter_profile, profile)

    channel_map = _role_map_from_profile(profile)
    capabilities = profile.get("capabilities", {})
    metadata = {
        "name": profile.get("name", fixture.name),
        "manufacturer": profile.get("manufacturer"),
        "model": profile.get("model"),
        "notes": profile.get("notes"),
        "manual_source": profile.get("manual_source"),
    }
    return LaserFixtureProfile(
        fixture_id=fixture.id,
        profile_name=fixture.profile,
        control_surface=str(profile.get("control_surface", "dmx")),
        fallback_surface=(
            str(profile["fallback_surface"]) if profile.get("fallback_surface") is not None else None
        ),
        dmx_channel_count=int(profile.get("channels", len(channel_map))),
        channel_map=channel_map,
        capabilities=capabilities if isinstance(capabilities, dict) else {},
        metadata=metadata,
        connections=profile.get("connections", {})
        if isinstance(profile.get("connections"), dict)
        else {},
        specifications=profile.get("specifications", {})
        if isinstance(profile.get("specifications"), dict)
        else {},
        safety=profile.get("safety", {}) if isinstance(profile.get("safety"), dict) else {},
        adapter_assumption=bool(profile.get("adapter_assumption", False)),
    )


def build_laser_profiles(
    fixtures: list[FixtureConfig],
    fixtures_dir: Path,
) -> dict[str, LaserFixtureProfile]:
    """Resolve all configured laser fixture profiles."""
    return {
        fixture.id: resolve_laser_profile(fixture, fixtures_dir)
        for fixture in fixtures
        if fixture.type == "laser"
    }
