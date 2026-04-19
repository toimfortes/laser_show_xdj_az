import pytest

import photonic_synesthesia.showplan as showplan
import photonic_synesthesia.showplan.types as showplan_types
from photonic_synesthesia.core.exceptions import ShowplanError
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
        allow_minimal_fallback=True,
    )
    assert isinstance(resolved, list)
    assert resolved


def test_cli_and_model_payloads_share_creative_profiles_source() -> None:
    """Regression: cli and showplan.model_payloads must reference the same
    CREATIVE_PROFILES object, not duplicated copies. Drift was flagged in
    the 2026-04-19 showplan review (Finding #4).
    """
    from photonic_synesthesia.showplan.creative_profiles import CREATIVE_PROFILES
    from photonic_synesthesia.showplan.model_payloads import (
        _CREATIVE_PROFILES as model_payloads_ref,
    )
    from photonic_synesthesia.ui.cli import _CREATIVE_PROFILES as cli_ref

    assert cli_ref is CREATIVE_PROFILES
    assert model_payloads_ref is CREATIVE_PROFILES


def test_showplan_sections_resolve_raises_when_no_builder_injected() -> None:
    """Missing default_show_sections_fn is a wiring bug, not a degradation path."""
    with pytest.raises(ShowplanError):
        resolve_show_sections(
            None,
            [],
            64.0,
            track_seed="fixture",
        )


def test_showplan_build_show_catalog_entry_is_callable() -> None:
    assert callable(build_show_catalog_entry)
    assert callable(build_semantic_profile)
