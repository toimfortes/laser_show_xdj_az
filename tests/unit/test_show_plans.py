from __future__ import annotations

from photonic_synesthesia.integrations.show_plans import (
    sanitize_show_plan_key,
    show_plan_path,
)


def test_sanitize_show_plan_key_is_collision_resistant_for_similar_names() -> None:
    key_a = sanitize_show_plan_key("Artist | Song!")
    key_b = sanitize_show_plan_key("Artist / Song?")

    assert key_a != key_b
    assert "__" in key_a
    assert "__" in key_b


def test_show_plan_path_uses_hashed_stem_suffix() -> None:
    path = show_plan_path("Artist|Song")

    assert path.suffix == ".json"
    assert "__" in path.stem
