"""Task 2 acceptance: showplan primitives (recipes, phasers, tags, timeline_flags).

One file covering all four new modules. Cycle-1 panel UF-25 family:
each test asserts the SPECIFIC content this task introduces, not just
key presence — so the test is genuinely red before Task 2 lands.
"""

from __future__ import annotations

from photonic_synesthesia.showplan import (
    build_phaser_bundle,
    build_recipe_bundle,
    build_section_tags,
    derive_timeline_flags,
)


# --- recipes.build_recipe_bundle -------------------------------------------

def test_build_recipe_bundle_high_energy_role_emits_fan_open_next_position() -> None:
    """High-energy roles (build/drop and suffixed variants) point to fan_open."""
    bundle = build_recipe_bundle(
        section_role="drop_1",
        lead_family="laser",
        target_mode="overhead",
        cue_family_id="venue::drop_1::laser",
    )
    assert bundle["next_positions"] == ["fan_open"]
    assert bundle["recipe_lines"][0]["selection"] == "laser:drop_1"
    assert bundle["recipe_lines"][0]["preset"] == "drop_1:overhead"


def test_build_recipe_bundle_low_energy_role_emits_lead_home() -> None:
    """Non-high-energy roles return the lead family's home position."""
    bundle = build_recipe_bundle(
        section_role="breakdown",
        lead_family="wash",
        target_mode="overhead",
        cue_family_id="venue::breakdown::wash",
    )
    assert bundle["next_positions"] == ["wash:home"]


def test_build_recipe_bundle_handles_suffixed_roles() -> None:
    """Suffix variants (build_1, build_2, drop_variation) hit high-energy path."""
    for role in ("build_1", "build_2", "drop_1", "drop_variation"):
        bundle = build_recipe_bundle(
            section_role=role, lead_family="laser",
            target_mode="overhead", cue_family_id=f"v::{role}::laser",
        )
        assert bundle["next_positions"] == ["fan_open"], f"role {role} should be high-energy"


# --- phasers.build_phaser_bundle -------------------------------------------

def test_build_phaser_bundle_high_energy_emits_pressure_family() -> None:
    bundle = build_phaser_bundle(section_role="drop_1", lead_family="laser")
    assert bundle[0]["family"] == "pressure"
    assert bundle[0]["target"] == "laser"


def test_build_phaser_bundle_low_energy_emits_breathing_family() -> None:
    bundle = build_phaser_bundle(section_role="breakdown", lead_family="wash")
    assert bundle[0]["family"] == "breathing"
    assert bundle[0]["target"] == "wash"


# --- tags.build_section_tags -----------------------------------------------

def test_build_section_tags_emits_role_lead_venue_laser_quad() -> None:
    tags = build_section_tags(
        section_role="drop_1",
        lead_family="laser",
        venue_mode="small_room_50_100",
        laser_enabled=True,
    )
    assert tags == ["role:drop_1", "lead:laser", "venue:small_room_50_100", "laser:on"]


def test_build_section_tags_laser_off_when_disabled() -> None:
    tags = build_section_tags(
        section_role="intro", lead_family="wash",
        venue_mode="small_room_50_100", laser_enabled=False,
    )
    assert tags[-1] == "laser:off"


# --- timeline_flags.derive_timeline_flags ---------------------------------

def test_derive_timeline_flags_emits_phrase_head_per_section() -> None:
    flags = derive_timeline_flags([
        {"id": "sec-0", "start_seconds": 0.0, "end_seconds": 16.0},
        {"id": "sec-1", "start_seconds": 16.0, "end_seconds": 32.0},
    ])
    assert len(flags) == 2
    assert flags[0]["id"] == "sec-0:phrase_head"
    assert flags[0]["kind"] == "phrase_head"
    assert flags[0]["at_seconds"] == 0.0
    assert flags[0]["payload"] == {"section_id": "sec-0"}
    assert flags[1]["id"] == "sec-1:phrase_head"


def test_derive_timeline_flags_emits_transition_typed_flag_when_intent_present() -> None:
    flags = derive_timeline_flags([
        {
            "id": "sec-1", "start_seconds": 16.0, "end_seconds": 32.0,
            "transition_intent": {"type": "bloom"},
        },
    ])
    flag_ids = [f["id"] for f in flags]
    assert "sec-1:phrase_head" in flag_ids
    assert "sec-1:bloom" in flag_ids
    bloom = next(f for f in flags if f["id"] == "sec-1:bloom")
    assert bloom["kind"] == "bloom"
    assert bloom["payload"] == {"section_id": "sec-1"}


def test_derive_timeline_flags_skips_sections_without_id() -> None:
    flags = derive_timeline_flags([
        {"start_seconds": 0.0, "end_seconds": 1.0},  # no id
    ])
    assert flags == []


def test_derive_timeline_flags_returns_stable_order() -> None:
    """Order matters because TriggerRouterNode iterates and pre-populates."""
    flags = derive_timeline_flags([
        {"id": "sec-0", "start_seconds": 0.0, "end_seconds": 8.0,
         "transition_intent": {"type": "handoff"}},
        {"id": "sec-1", "start_seconds": 8.0, "end_seconds": 16.0},
    ])
    assert [f["id"] for f in flags] == [
        "sec-0:phrase_head", "sec-0:handoff", "sec-1:phrase_head",
    ]
