import photonic_synesthesia.showplan as showplan
import photonic_synesthesia.showplan.types as showplan_types


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
