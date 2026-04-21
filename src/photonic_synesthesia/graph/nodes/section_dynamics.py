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
    intensity_multiplier: float
    motion_multiplier: float
    strobe_level: float
    laser_enabled: bool
    movers_enabled: bool
    washes_enabled: bool
    leds_enabled: bool
    panel_family: Literal["wash", "led"] | None


def _float_or_default(value: Any, default: float) -> float:
    try:
        resolved = float(value)
    except (TypeError, ValueError):
        return default
    return resolved if math.isfinite(resolved) else default


def _bool_or_default(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
        return default
    return bool(value)


def _snapshot_for_state(state: PhotonicState) -> dict[str, Any]:
    snapshot = dict(state.get("playback_snapshot") or {})
    if snapshot:
        return snapshot
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


def resolve_active_section_dynamics(state: PhotonicState) -> SectionDynamics:
    """Resolve the authored section active at the current playhead."""

    current_section = _active_section(_snapshot_for_state(state))
    section_id = None
    if isinstance(current_section, dict) and current_section.get("id") is not None:
        section_id = str(current_section.get("id"))

    return SectionDynamics(
        section_id=section_id,
        current_section=current_section,
        intensity_multiplier=_float_or_default(
            current_section.get("intensity_multiplier") if isinstance(current_section, dict) else None,
            1.0,
        ),
        motion_multiplier=_float_or_default(
            current_section.get("motion_multiplier") if isinstance(current_section, dict) else None,
            1.0,
        ),
        strobe_level=_float_or_default(
            current_section.get("strobe_level") if isinstance(current_section, dict) else None,
            0.0,
        ),
        laser_enabled=_bool_or_default(
            current_section.get("laser_enabled") if isinstance(current_section, dict) else None,
            True,
        ),
        movers_enabled=_bool_or_default(
            current_section.get("movers_enabled") if isinstance(current_section, dict) else None,
            True,
        ),
        washes_enabled=_bool_or_default(
            current_section.get("washes_enabled") if isinstance(current_section, dict) else None,
            True,
        ),
        leds_enabled=_bool_or_default(
            current_section.get("leds_enabled") if isinstance(current_section, dict) else None,
            True,
        ),
        panel_family=_panel_family(current_section),
    )
