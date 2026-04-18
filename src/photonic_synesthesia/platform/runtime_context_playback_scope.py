"""Live playback scope targeting helpers for runtime context."""

from __future__ import annotations

from typing import Any


def section_ids_for_scope(show_sections: list[dict[str, Any]], playhead_seconds: float, scope: str) -> set[str]:
    if not show_sections:
        return set()
    if scope in {"track", "set"}:
        return {str(section.get("id") or "") for section in show_sections}
    active_index = len(show_sections) - 1
    for index, section in enumerate(show_sections):
        start = float(section.get("start_seconds") or 0.0)
        end = float(section.get("end_seconds") or start)
        if start <= playhead_seconds < end:
            active_index = index
            break
    if scope == "current_section":
        return {str(show_sections[active_index].get("id") or "")}
    next_index = min(active_index + 1, max(0, len(show_sections) - 1))
    return {str(show_sections[next_index].get("id") or "")}
