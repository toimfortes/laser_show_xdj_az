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
