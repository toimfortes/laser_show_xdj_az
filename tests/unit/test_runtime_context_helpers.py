from photonic_synesthesia.platform.runtime_context_normalization import (
    clamp,
    normalize_metadata_source,
    normalize_operator_intent,
    normalize_operator_scope,
    normalize_operator_target,
    normalize_selection_mode,
    normalize_selection_variance,
    normalize_venue_mode,
)
from photonic_synesthesia.platform.runtime_context_operator_intents import (
    apply_operator_intent_to_section,
    intent_expired,
)
from photonic_synesthesia.platform.runtime_context_playback_scope import section_ids_for_scope
from photonic_synesthesia.platform.runtime_context_section_mutations import (
    promote_family_to_hero,
    set_family_intensity,
)


def test_normalize_selection_mode_falls_back_to_procedural() -> None:
    assert normalize_selection_mode("unknown-mode") == "procedural"


def test_normalize_selection_variance_clamps_to_unit_interval() -> None:
    assert normalize_selection_variance(1.7) == 1.0
    assert normalize_selection_variance(-1) == 0.0


def test_normalize_venue_mode_accepts_medium_room() -> None:
    assert normalize_venue_mode("medium-room-150-400") == "medium_room_150_400"


def test_operator_normalizers_accept_known_values() -> None:
    assert normalize_operator_intent("promote-washes") == "promote_washes"
    assert normalize_operator_scope("next-phrase") == "next_phrase"
    assert normalize_operator_target("lasers") == "lasers"


def test_normalize_metadata_source_and_clamp() -> None:
    assert normalize_metadata_source("Pro-DJ-Link") == "pro_dj_link"
    assert clamp(2.0, 0.0, 1.0) == 1.0


def test_section_ids_for_scope_returns_current_section() -> None:
    show_sections = [
        {"id": "a", "start_seconds": 0.0, "end_seconds": 8.0},
        {"id": "b", "start_seconds": 8.0, "end_seconds": 16.0},
    ]
    assert section_ids_for_scope(show_sections, 2.0, "current_section") == {"a"}


def test_set_family_intensity_updates_fixture_roles_and_cue_recipe_family() -> None:
    section = {
        "fixture_role_map": {"laser": {"intensity_ceiling": 1.0}},
        "cue_recipe": {
            "fixture_role_map": {"laser": {"intensity_ceiling": 1.0}},
            "families": {"laser": {"intensity_ceiling": 1.0}},
        },
    }

    set_family_intensity(section, "laser", 0.5)

    assert section["fixture_role_map"]["laser"]["intensity_ceiling"] == 0.5
    assert section["cue_recipe"]["fixture_role_map"]["laser"]["intensity_ceiling"] == 0.5
    assert section["cue_recipe"]["families"]["laser"]["intensity_ceiling"] == 0.5


def test_promote_family_to_hero_updates_fixture_roles_and_cue_recipe() -> None:
    section = {
        "lead_family": "mover",
        "fixture_role_map": {"mover": {"role": "hero"}, "wash": {"role": "support"}},
        "cue_family_id": "small_room_50_100::intro::mover",
        "cue_recipe": {
            "lead_family": "mover",
            "cue_family_id": "small_room_50_100::intro::mover",
            "fixture_role_map": {"mover": {"role": "hero"}, "wash": {"role": "support"}},
        },
    }

    promote_family_to_hero(section, "wash")

    assert section["lead_family"] == "wash"
    assert section["fixture_role_map"]["wash"]["role"] == "hero"
    assert section["cue_recipe"]["lead_family"] == "wash"


def test_intent_expired_at_threshold() -> None:
    assert intent_expired({"expires_at": "at:5"}, [], 5.1, 10.0) is True


def test_apply_operator_intent_to_section_reduces_strobe() -> None:
    updated = apply_operator_intent_to_section(
        {
            "strobe_level": 0.8,
            "strobe_profile": {"ceiling": 0.9, "floor": 0.2},
            "cue_recipe": {},
        },
        intent="less_strobe",
        target="strobes",
        amount=0.5,
        duration_seconds=60.0,
    )

    assert updated["strobe_level"] == 0.4
    assert updated["strobe_profile"]["ceiling"] == 0.45
