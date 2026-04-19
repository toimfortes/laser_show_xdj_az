"""Public facade for show-planning domain helpers."""

from __future__ import annotations

from photonic_synesthesia.showplan.catalog import build_show_catalog_entry
from photonic_synesthesia.showplan.cue_recipe import build_cue_recipe
from photonic_synesthesia.showplan.laser_program import build_laser_program
from photonic_synesthesia.showplan.model_payloads import build_catalog_model_payload
from photonic_synesthesia.showplan.sections import resolve_show_sections
from photonic_synesthesia.showplan.selection import select_section_patterns
from photonic_synesthesia.showplan.semantic_profile import build_semantic_profile
from photonic_synesthesia.showplan.validation import anti_template_validation

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
