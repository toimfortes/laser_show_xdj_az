"""Public facade for show-planning domain helpers."""

from __future__ import annotations

from typing import Any

from photonic_synesthesia.showplan.semantic_profile import build_semantic_profile


def _unimplemented(*args: Any, **kwargs: Any) -> Any:
    raise NotImplementedError("showplan facade entrypoint not implemented yet")


build_show_catalog_entry = _unimplemented
resolve_show_sections = _unimplemented
build_cue_recipe = _unimplemented
build_laser_program = _unimplemented
anti_template_validation = _unimplemented
select_section_patterns = _unimplemented
build_catalog_model_payload = _unimplemented

__all__ = [
    "build_show_catalog_entry",
    "build_semantic_profile",
    "resolve_show_sections",
    "build_cue_recipe",
    "build_laser_program",
    "anti_template_validation",
    "select_section_patterns",
    "build_catalog_model_payload",
]
