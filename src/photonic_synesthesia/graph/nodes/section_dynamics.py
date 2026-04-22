"""Shared helpers for resolving live section dynamics from playback state."""

from __future__ import annotations

import math
from typing import Any, Literal, TypedDict

from photonic_synesthesia.core.state import PhotonicState
from photonic_synesthesia.platform.runtime_context import get_shared_playback_context


class SectionDynamics(TypedDict):
    """Normalized active-section dynamics exposed to runtime nodes."""

    section_id: str | None
    current_section: dict[str, Any] | None
    scene_id: str | None
    fixture_mode: str
    laser_pattern: str
    mover_pattern: str
    wash_pattern: str
    led_pattern: str
    intensity_multiplier: float
    motion_multiplier: float
    strobe_level: float
    laser_enabled: bool
    movers_enabled: bool
    washes_enabled: bool
    leds_enabled: bool
    panel_family: Literal["wash", "led"] | None


LASER_PATTERN_GEOMETRY_FAMILY_MAP: dict[str, str] = {
    "fan": "fan",
    "beam_fan_narrow": "fan",
    "beam_fan_wide": "fan",
    "cross_room_fans": "fan",
    "thin_scan": "scan",
    "scan_slice": "scan",
    "wave": "scan",
    "vertical_rake": "rake",
    "horizontal_rake": "rake",
    "liquid_sky": "sky",
    "cone": "cone",
    "tunnel": "tunnel",
    "spiral_tunnel": "tunnel",
    "crisscross": "lattice",
    "lattice": "lattice",
    "rotor": "helix",
    "helix": "helix",
    "spirograph": "helix",
    "wave_trace": "helix",
    "loop_trace": "helix",
    "roll_trace": "helix",
    "burst_fan": "burst",
    "fan_burst": "burst",
    "starburst": "burst",
    "shutter_hits": "burst",
    "mixed_beam_fx": "burst",
    "alternating_beam_groups": "grouped",
    "split_zone_beams": "grouped",
    "target_split_chase": "grouped",
    "static_beam": "array",
    "dual_beam": "array",
    "tri_beam": "array",
    "point_array": "array",
    "spoke_wheel": "array",
    "sheet": "sheet",
    "circle_trace": "trace",
    "vertical_line_trace": "trace",
    "horizontal_line_trace": "trace",
    "triangle_trace": "trace",
    "square_trace": "trace",
    "pentagon_trace": "trace",
    "hexagon_trace": "trace",
    "target_step_chase": "sequence",
    "target_bounce_chase": "sequence",
    "target_rotate_chase": "sequence",
    "target_ring_chase": "sequence",
    "beam_sequence_clockwise": "sequence",
    "beam_sequence_counterclockwise": "sequence",
}

LASER_GEOMETRY_FAMILY_DMX_PATTERN_MAP: dict[str, int] = {
    "sky": 0,
    "fan": 4,
    "sheet": 6,
    "cone": 8,
    "tunnel": 10,
    "scan": 12,
    "lattice": 14,
    "rake": 16,
    "helix": 18,
    "grouped": 20,
    "trace": 22,
    "burst": 24,
    "sequence": 26,
    "array": 28,
}

MOVER_PATTERN_FAMILY_MAP: dict[str, str] = {
    "hold": "hold",
    "rise": "rise",
    "tilt_rise": "rise",
    "ping_pong_tilt": "rise",
    "cross_sweep": "cross",
    "pan_sweep": "cross",
    "mirror_fan": "cross",
    "line_bounce": "cross",
    "circle": "shape",
    "figure_eight": "shape",
    "leaf": "shape",
    "square": "shape",
    "diamond": "shape",
    "snap_hits": "hits",
    "hit_sweep": "hits",
    "drift": "drift",
}

WASH_PATTERN_RENDER_MODE_MAP: dict[str, str] = {
    "ambient": "ambient",
    "static": "ambient",
    "fade": "fade",
    "breakdown_glow": "fade",
    "bloom": "bloom",
    "build_ramp": "bloom",
    "center_out": "bloom",
    "outside_in": "bloom",
    "gradient_roll": "bloom",
    "punch": "punch",
    "downbeat_hit": "punch",
    "drop_slam": "punch",
    "white_peak": "punch",
    "breath": "breath",
}

LED_PATTERN_RENDER_MODE_MAP: dict[str, str] = {
    "pulse": "pulse",
    "static": "pulse",
    "chase": "chase",
    "snake": "chase",
    "rotating_line": "chase",
    "sparkle": "sparkle",
    "fizzle": "sparkle",
    "audio_spectrum": "sparkle",
    "ramp": "ramp",
    "vertical_build": "ramp",
    "vertical_offset": "ramp",
    "horizontal_ramp": "ramp",
    "horizontal_lines": "ramp",
    "fade": "fade",
}


def _float_or_default(value: Any, default: float) -> float:
    try:
        resolved = float(value)
    except (TypeError, ValueError):
        return default
    return resolved if math.isfinite(resolved) else default


def _bool_or_default(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
        return default
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            return default
        return bool(value)
    return default


def _string_or_default(value: Any, default: str = "", *, allow_numeric: bool = False) -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    if allow_numeric and isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return default


def _snapshot_for_state(state: PhotonicState) -> dict[str, Any]:
    if "playback_snapshot" in state:
        raw_snapshot = state.get("playback_snapshot")
        if isinstance(raw_snapshot, dict):
            return dict(raw_snapshot)
        return {}
    playback = get_shared_playback_context()
    if playback is None:
        return {}
    return playback.snapshot()


def _active_section(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve the authored section active at the current playhead.

    This policy is intentionally asymmetric:
    - before the first section, or inside a gap between sections: return None
    - past the final effective end: return the last section

    That differs from the older runtime lookup paths that always fell back to
    the last section on any no-match.
    """
    raw_sections = snapshot.get("show_sections")
    if not isinstance(raw_sections, list):
        return None

    sections = [section for section in raw_sections if isinstance(section, dict)]
    if not sections:
        return None

    playhead = _float_or_default(snapshot.get("playhead_seconds"), 0.0)
    for section in sections:
        start = _float_or_default(section.get("start_seconds"), 0.0)
        end = _float_or_default(section.get("end_seconds"), start)
        if start <= playhead < max(end, start + 1e-6):
            return section

    last_section = sections[-1]
    last_start = _float_or_default(last_section.get("start_seconds"), 0.0)
    last_end = _float_or_default(last_section.get("end_seconds"), last_start)
    if playhead >= max(last_end, last_start + 1e-6):
        return last_section
    return None


def _panel_family(section: dict[str, Any] | None) -> Literal["wash", "led"] | None:
    if not isinstance(section, dict):
        return None

    lead_family = str(section.get("lead_family") or "")
    if lead_family in {"wash", "led"}:
        return lead_family

    fixture_role_map = section.get("fixture_role_map")
    if not isinstance(fixture_role_map, dict):
        return None

    has_wash = isinstance(fixture_role_map.get("wash"), dict)
    has_led = isinstance(fixture_role_map.get("led"), dict)
    if has_wash and not has_led:
        return "wash"
    if has_led and not has_wash:
        return "led"
    return None


def resolve_laser_pattern_override(pattern: str) -> tuple[int | None, str | None]:
    geometry_family = LASER_PATTERN_GEOMETRY_FAMILY_MAP.get(pattern)
    if geometry_family is None:
        return None, None
    return LASER_GEOMETRY_FAMILY_DMX_PATTERN_MAP.get(geometry_family), geometry_family


def resolve_mover_pattern_family(pattern: str) -> str | None:
    return MOVER_PATTERN_FAMILY_MAP.get(pattern)


def resolve_panel_render_mode(
    pattern: str,
    family: Literal["wash", "led"] | None,
) -> str | None:
    if family == "wash":
        return WASH_PATTERN_RENDER_MODE_MAP.get(pattern)
    if family == "led":
        return LED_PATTERN_RENDER_MODE_MAP.get(pattern)
    return LED_PATTERN_RENDER_MODE_MAP.get(pattern) or WASH_PATTERN_RENDER_MODE_MAP.get(pattern)


def resolve_active_section_dynamics(state: PhotonicState) -> SectionDynamics:
    """Resolve the authored section active at the current playhead."""

    current_section = _active_section(_snapshot_for_state(state))
    section = current_section if isinstance(current_section, dict) else None
    section_id = _string_or_default(section.get("id") if section is not None else None, allow_numeric=True) or None
    scene_id = _string_or_default(section.get("scene_id") if section is not None else None, allow_numeric=True) or None

    return SectionDynamics(
        section_id=section_id,
        current_section=current_section,
        scene_id=scene_id,
        fixture_mode=_string_or_default(section.get("fixture_mode") if section is not None else None),
        laser_pattern=_string_or_default(section.get("laser_pattern") if section is not None else None),
        mover_pattern=_string_or_default(section.get("mover_pattern") if section is not None else None),
        wash_pattern=_string_or_default(section.get("wash_pattern") if section is not None else None),
        led_pattern=_string_or_default(section.get("led_pattern") if section is not None else None),
        intensity_multiplier=_float_or_default(
            section.get("intensity_multiplier") if section is not None else None,
            1.0,
        ),
        motion_multiplier=_float_or_default(
            section.get("motion_multiplier") if section is not None else None,
            1.0,
        ),
        strobe_level=_float_or_default(
            section.get("strobe_level") if section is not None else None,
            0.0,
        ),
        laser_enabled=_bool_or_default(
            section.get("laser_enabled") if section is not None else None,
            True,
        ),
        movers_enabled=_bool_or_default(
            section.get("movers_enabled") if section is not None else None,
            True,
        ),
        washes_enabled=_bool_or_default(
            section.get("washes_enabled") if section is not None else None,
            True,
        ),
        leds_enabled=_bool_or_default(
            section.get("leds_enabled") if section is not None else None,
            True,
        ),
        panel_family=_panel_family(current_section),
    )
