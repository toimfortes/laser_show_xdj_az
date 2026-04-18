import photonic_synesthesia.showplan as showplan
import photonic_synesthesia.showplan.types as showplan_types
from photonic_synesthesia.showplan import (
    build_semantic_profile,
    build_show_catalog_entry,
    resolve_show_sections,
)


def test_showplan_facade_import_smoke() -> None:
    for name in (
        "build_show_catalog_entry",
        "build_semantic_profile",
        "resolve_show_sections",
        "build_cue_recipe",
        "build_laser_program",
        "anti_template_validation",
        "select_section_patterns",
        "build_catalog_model_payload",
    ):
        assert hasattr(showplan, name)


def test_showplan_types_import_smoke() -> None:
    assert hasattr(showplan_types, "ShowSection")


def test_showplan_sections_resolve_show_sections_matches_existing_shape() -> None:
    resolved = resolve_show_sections(
        {"show_sections": [{"id": "section_000", "label": "Auto Intro", "kind": "intro", "start_seconds": 0.0, "end_seconds": 0.25}]},
        [],
        64.0,
        track_seed="fixture",
    )
    assert isinstance(resolved, list)
    assert resolved


def test_showplan_build_show_catalog_entry_is_callable() -> None:
    assert callable(build_show_catalog_entry)
    assert callable(build_semantic_profile)
