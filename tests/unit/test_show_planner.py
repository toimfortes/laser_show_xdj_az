import photonic_synesthesia.ui.cli as cli_module
from photonic_synesthesia.showplan import (
    anti_template_validation,
    build_cue_recipe,
    build_laser_program,
    select_section_patterns,
)
from photonic_synesthesia.ui.cli import (
    _LASER_PATTERN_POOLS,
    _default_show_sections,
    _resolve_show_sections,
    _transition_context,
)


def test_build_laser_program_returns_phrase_roles() -> None:
    payload = build_laser_program(
        track_seed="fixture",
        base_pattern="fan",
        kind="drop",
        context="drop_launch",
        ordinal=0,
        profile={},
        venue_mode="small_room_50_100",
    )
    assert payload["launch"]["label"] == "Launch Hook"


def test_anti_template_validation_returns_status() -> None:
    result = anti_template_validation(
        track_key="artist|track",
        show_sections=[],
        semantic_profile=None,
        recent_catalog_entries=[],
    )
    assert "status" in result


def test_select_section_patterns_returns_all_families() -> None:
    result = select_section_patterns(
        kind="drop",
        context="drop_launch",
        profile={},
        track_seed="fixture",
        marker_name="Drop A",
        ordinal=0,
        previous_patterns={"laser": None, "mover": None, "wash": None, "led": None},
        pattern_history=None,
        usage_count_by_family=None,
        semantic_profile=None,
        selection_mode="procedural",
        energy_scale=1.0,
        selection_variance=0.0,
    )
    assert set(result) == {"laser", "mover", "wash", "led"}


def test_build_cue_recipe_returns_expected_version() -> None:
    payload = build_cue_recipe(
        kind="drop",
        context="drop_launch",
        laser_pattern="fan",
        mover_pattern="sweep",
        wash_pattern="ambient",
        led_pattern="pulse",
        laser_enabled=True,
        movers_enabled=True,
        washes_enabled=True,
        leds_enabled=True,
        section_role="drop_1",
        venue_mode="small_room_50_100",
        venue_profile={"mode": "small_room_50_100"},
        transition_intent={"type": "bloom"},
        cue_family_id="small_room_50_100::drop_1::mover",
        lead_family="mover",
        fixture_role_map={"mover": {"role": "hero"}},
        capability_graph={"mover": {}},
        capability_notes=[],
        metadata_confidence=None,
    )
    assert payload["version"] == 6


def _markers() -> list[dict[str, object]]:
    return [
        {"name": "Intro", "kind": "intro", "start_seconds": 0.0, "energy_hint": 5},
        {"name": "Build A", "kind": "build", "start_seconds": 64.0, "energy_hint": 6},
        {"name": "Drop A", "kind": "drop", "start_seconds": 96.0, "energy_hint": 8},
        {"name": "Breakdown", "kind": "breakdown", "start_seconds": 160.0, "energy_hint": 4},
        {"name": "Build B", "kind": "build", "start_seconds": 208.0, "energy_hint": 7},
        {"name": "Drop B", "kind": "drop", "start_seconds": 240.0, "energy_hint": 8},
        {"name": "Outro", "kind": "outro", "start_seconds": 304.0, "energy_hint": 5},
    ]


def test_show_planner_varies_across_track_seed() -> None:
    sections_a = _default_show_sections(_markers(), 360.0, track_seed="artist-a|track-a")
    sections_b = _default_show_sections(_markers(), 360.0, track_seed="artist-b|track-b")

    signatures_a = [
        (
            section["laser_pattern"],
            section["laser_variant"]["label"],
            section["laser_expression"]["label"],
            section["laser_expression"]["geometry_family"],
            section["laser_expression"]["color_mode"],
            section["mover_pattern"],
            section["mover_variant"]["label"],
            section["wash_pattern"],
            section["wash_variant"]["label"],
            section["led_pattern"],
            section["led_variant"]["label"],
            section["strobe_level"],
            section["strobe_profile"]["mode"],
            section["strobe_profile"]["shape"],
            section["laser_enabled"],
            section["leds_enabled"],
        )
        for section in sections_a
    ]
    signatures_b = [
        (
            section["laser_pattern"],
            section["laser_variant"]["label"],
            section["laser_expression"]["label"],
            section["laser_expression"]["geometry_family"],
            section["laser_expression"]["color_mode"],
            section["mover_pattern"],
            section["mover_variant"]["label"],
            section["wash_pattern"],
            section["wash_variant"]["label"],
            section["led_pattern"],
            section["led_variant"]["label"],
            section["strobe_level"],
            section["strobe_profile"]["mode"],
            section["strobe_profile"]["shape"],
            section["laser_enabled"],
            section["leds_enabled"],
        )
        for section in sections_b
    ]

    assert signatures_a != signatures_b


def test_laser_catalog_is_substantially_expanded() -> None:
    patterns = {
        pattern
        for pool in _LASER_PATTERN_POOLS.values()
        for pattern in pool
    }

    assert len(patterns) >= 39


def test_repeated_drops_get_variation() -> None:
    sections = _default_show_sections(_markers(), 360.0, track_seed="same-song")
    drops = [section for section in sections if section["kind"] == "drop"]

    assert len(drops) == 2
    first_signature = (
        drops[0]["laser_pattern"],
        drops[0]["laser_variant"]["label"],
        drops[0]["laser_expression"]["label"],
        drops[0]["laser_expression"]["target_bias"],
        drops[0]["mover_pattern"],
        drops[0]["mover_variant"]["label"],
        drops[0]["wash_pattern"],
        drops[0]["wash_variant"]["label"],
        drops[0]["led_pattern"],
        drops[0]["led_variant"]["label"],
        drops[0]["strobe_level"],
        drops[0]["strobe_profile"]["shape"],
    )
    second_signature = (
        drops[1]["laser_pattern"],
        drops[1]["laser_variant"]["label"],
        drops[1]["laser_expression"]["label"],
        drops[1]["laser_expression"]["target_bias"],
        drops[1]["mover_pattern"],
        drops[1]["mover_variant"]["label"],
        drops[1]["wash_pattern"],
        drops[1]["wash_variant"]["label"],
        drops[1]["led_pattern"],
        drops[1]["led_variant"]["label"],
        drops[1]["strobe_level"],
        drops[1]["strobe_profile"]["shape"],
    )

    assert first_signature != second_signature
    assert [
        drops[0]["laser_program"]["sustain"][0]["pattern"],
        drops[0]["laser_program"]["sustain"][1]["pattern"],
        drops[0]["laser_program"]["fills"][0]["pattern"],
        drops[0]["laser_program"]["fills"][1]["pattern"],
    ] != [
        drops[1]["laser_program"]["sustain"][0]["pattern"],
        drops[1]["laser_program"]["sustain"][1]["pattern"],
        drops[1]["laser_program"]["fills"][0]["pattern"],
        drops[1]["laser_program"]["fills"][1]["pattern"],
    ]


def test_build_and_drop_transitions_escalate() -> None:
    sections = _default_show_sections(_markers(), 360.0, track_seed="transition-test")

    intro = sections[0]
    build = sections[1]
    drop = sections[2]
    breakdown = sections[3]

    assert build["motion_multiplier"] > intro["motion_multiplier"]
    assert drop["strobe_level"] > build["strobe_level"]
    assert drop["laser_enabled"] is True
    assert breakdown["washes_enabled"] is True
    assert build["strobe_profile"]["mode"] == "riser"
    assert drop["strobe_profile"]["mode"] in {"impact", "burst"}
    assert "label" in drop["laser_variant"]
    assert "label" in drop["laser_expression"]
    assert drop["laser_expression"]["content_family"] in {"beam", "abstract", "transition"}
    assert drop["laser_expression"]["geometry_family"] in {"burst", "grouped", "tunnel", "lattice", "rake", "sky", "cone", "scan", "fan", "helix", "array", "sheet", "trace", "sequence"}
    assert drop["laser_expression"]["target_strategy"]
    assert drop["laser_expression"]["blanking_strategy"]
    assert drop["laser_expression"]["color_strategy"]
    assert drop["laser_expression"]["transition_role"] in {
        "drop_launch",
        "drop_variation",
        "build_riser",
        "breakdown_release",
        "intro_set",
        "outro_release",
    }
    envelope = drop["laser_expression"]["phrase_envelope"]
    assert envelope["launch_bars"] > 0
    assert envelope["normalize_after_bars"] > 0
    assert envelope["launch_intensity"] > envelope["sustain_intensity"]
    assert len(drop["laser_expression"]["variation_plan"]) >= 2
    assert drop["strobe_profile"]["ceiling"] >= drop["strobe_profile"]["floor"]
    laser_program = drop["laser_program"]
    assert laser_program["version"] == 3
    assert laser_program["phrase_role"] in {"drop_launch", "drop_variation", "build_riser", "breakdown_release", "intro_set", "outro_release"}
    assert laser_program["zone_policy"] in {"overhead_only", "mixed_air", "crowd_punctuate", "overhead_bias"}
    assert laser_program["launch"]["pattern"]
    assert laser_program["release"]["pattern"]
    assert laser_program["launch"]["label"] == "Launch Hook"
    assert laser_program["release"]["label"] == "Release Hook"
    assert len(laser_program["sustain"]) == 2
    assert [look["label"] for look in laser_program["sustain"]] == ["Sustain A", "Sustain B"]
    assert laser_program["sustain"][0]["pattern"] != laser_program["launch"]["pattern"]
    assert len(laser_program["fills"]) == 2
    assert [look["label"] for look in laser_program["fills"]] == ["Fill A", "Fill B"]
    assert all(look["geometry_family"] for look in laser_program["sustain"])
    cue_recipe = drop["cue_recipe"]
    assert cue_recipe["version"] == 6
    assert cue_recipe["intent"] == laser_program["phrase_role"]
    assert cue_recipe["stage"] == "drop"
    assert cue_recipe["section_role"] == "drop_1"
    assert cue_recipe["venue_mode"] == "small_room_50_100"
    assert cue_recipe["cue_family_id"] == drop["cue_family_id"]
    assert cue_recipe["lead_family"] == drop["lead_family"]
    assert cue_recipe["timing_master"]
    assert cue_recipe["trigger_policy"]["confidence_tier"] == "degraded"
    assert cue_recipe["transition_intent"]["type"] == "bloom"
    assert cue_recipe["fixture_role_map"]["mover"]["role"] == "hero"
    assert cue_recipe["recipe_lines"]
    assert cue_recipe["phaser_bundle"]
    assert cue_recipe["recipe_bundle"]["cue_family_id"] == cue_recipe["cue_family_id"]
    assert cue_recipe["recipe_bundle"]["recipe_lines"] == cue_recipe["recipe_lines"]
    assert cue_recipe["families"]["laser"]["recipe_line"]["group_ref"]
    assert cue_recipe["families"]["mover"]["phaser_family"]["family"]
    assert cue_recipe["motif_ids"]
    assert cue_recipe["motif_primary"].startswith("role:")
    assert cue_recipe["families"]["laser"]["pattern"] == drop["laser_pattern"]
    assert cue_recipe["families"]["laser"]["zone_policy"] == laser_program["zone_policy"]
    assert cue_recipe["families"]["mover"]["group"]
    assert cue_recipe["families"]["mover"]["role"] == "hero"


def test_show_sections_include_normalized_roles_transition_intent_and_fixture_roles() -> None:
    sections = _default_show_sections(_markers(), 360.0, track_seed="same-song")

    assert [section["section_role"] for section in sections] == [
        "intro",
        "build_1",
        "drop_1",
        "breakdown",
        "build_2",
        "drop_variation",
        "outro",
    ]
    assert sections[0]["transition_intent"]["type"] == "set"
    assert sections[2]["transition_intent"]["type"] == "bloom"
    assert sections[3]["transition_intent"]["type"] == "suckout"
    assert sections[0]["venue_mode"] == "small_room_50_100"
    assert sections[0]["cue_family_id"] == "small_room_50_100::intro::wash"
    assert sections[0]["fixture_role_map"]["wash"]["role"] == "hero"
    assert sections[2]["lead_family"] == "mover"
    assert sections[5]["lead_family"] == "led"


def test_medium_room_adjusts_venue_defaults_and_laser_policy() -> None:
    small_sections = _default_show_sections(
        _markers(),
        360.0,
        track_seed="same-song",
        venue_mode="small_room_50_100",
    )
    medium_sections = _default_show_sections(
        _markers(),
        360.0,
        track_seed="same-song",
        venue_mode="medium_room_150_400",
    )

    assert small_sections[0]["venue_profile"]["readability_bias"] == "intimate"
    assert medium_sections[0]["venue_profile"]["readability_bias"] == "balanced"
    assert medium_sections[0]["motion_multiplier"] > small_sections[0]["motion_multiplier"]
    assert medium_sections[2]["cue_recipe"]["families"]["laser"]["zone_policy"] in {"overhead_bias", "mixed_air", "overhead_only"}
    assert small_sections[2]["cue_recipe"]["families"]["laser"]["zone_policy"] == "overhead_only"


def test_validator_enforces_single_hero_family_per_section() -> None:
    sections = _default_show_sections(_markers(), 360.0, track_seed="same-song")

    for section in sections:
        heroes = [
            family
            for family, payload in section["fixture_role_map"].items()
            if payload["role"] == "hero"
        ]
        assert heroes == [section["lead_family"]]
        cue_heroes = [
            family
            for family, payload in section["cue_recipe"]["fixture_role_map"].items()
            if payload["role"] == "hero"
        ]
        assert cue_heroes == [section["lead_family"]]


def test_validator_enforces_breakdown_withdrawal_and_small_room_strobe_caps() -> None:
    sections = _default_show_sections(_markers(), 360.0, track_seed="same-song", venue_mode="small_room_50_100")
    breakdown = next(section for section in sections if section["section_role"] == "breakdown")
    drop = next(section for section in sections if section["section_role"] == "drop_1")

    assert breakdown["lead_family"] == "wash"
    assert breakdown["laser_enabled"] is False
    assert breakdown["strobe_level"] == 0.0
    assert breakdown["strobe_profile"]["ceiling"] == 0.0
    assert breakdown["cue_recipe"]["families"]["laser"]["enabled"] is False
    assert breakdown["cue_recipe"]["families"]["laser"]["zone_policy"] == "overhead_only"
    assert drop["strobe_level"] <= 0.32


def test_validator_enforces_drop_variation_novelty_by_lead_family() -> None:
    sections = _default_show_sections(_markers(), 360.0, track_seed="same-song", venue_mode="small_room_50_100")
    drop_1 = next(section for section in sections if section["section_role"] == "drop_1")
    drop_2 = next(section for section in sections if section["section_role"] == "drop_variation")

    assert drop_1["lead_family"] != drop_2["lead_family"]


def test_small_room_capability_compiler_degrades_dense_laser_geometry() -> None:
    _, profile = cli_module._creative_profile("same-song", _markers())

    small_pattern, small_notes = cli_module._compatible_laser_pattern(
        base_pattern="point_array",
        kind="drop",
        context="drop_launch",
        profile=profile,
        section_role="drop_1",
        venue_mode="small_room_50_100",
    )
    medium_pattern, medium_notes = cli_module._compatible_laser_pattern(
        base_pattern="point_array",
        kind="drop",
        context="drop_launch",
        profile=profile,
        section_role="drop_1",
        venue_mode="medium_room_150_400",
    )

    assert small_pattern != "point_array"
    assert any(note.startswith("laser_pattern_degraded:") for note in small_notes)
    assert medium_pattern == "point_array"
    assert medium_notes == []


def test_sections_include_capability_graph_and_notes() -> None:
    sections = _default_show_sections(_markers(), 360.0, track_seed="same-song")
    intro = sections[0]

    assert intro["fixture_capability_graph"]["laser"]["allowed_geometries"]["intro"]
    assert isinstance(intro["capability_notes"], list)
    assert intro["motif_ids"]
    assert intro["motif_primary"].startswith("role:")
    assert intro["cue_recipe"]["fixture_capability_graph"]["laser"]["max_density_cap"] > 0
    assert intro["cue_recipe"]["capability_notes"] == intro["capability_notes"]
    assert intro["cue_recipe"]["recipe_bundle"]["cue_family_id"] == intro["cue_family_id"]
    assert intro["cue_recipe"]["phaser_bundle"][0]["family"]


def test_metadata_confidence_changes_trigger_policy_tier() -> None:
    degraded_sections = _default_show_sections(
        _markers(),
        360.0,
        track_seed="same-song",
        metadata_confidence={
            "transport_confidence": 0.3,
            "phrase_confidence": 0.25,
            "beatgrid_confidence": 0.4,
        },
    )
    strict_sections = _default_show_sections(
        _markers(),
        360.0,
        track_seed="same-song",
        metadata_confidence={
            "transport_confidence": 0.95,
            "phrase_confidence": 0.9,
            "beatgrid_confidence": 0.96,
        },
    )

    degraded_drop = next(section for section in degraded_sections if section["section_role"] == "drop_1")
    strict_drop = next(section for section in strict_sections if section["section_role"] == "drop_1")

    assert degraded_drop["cue_recipe"]["trigger_policy"]["confidence_tier"] == "degraded"
    assert degraded_drop["cue_recipe"]["trigger_policy"]["primary"] == "section_estimate"
    assert strict_drop["cue_recipe"]["trigger_policy"]["confidence_tier"] == "strict"
    assert strict_drop["cue_recipe"]["trigger_policy"]["primary"] == "phrase_head"


def test_show_fingerprint_preserves_motif_and_laser_repetition_counts() -> None:
    sections = [
        {
            "section_role": "drop_1",
            "lead_family": "laser",
            "transition_intent": {"type": "bloom"},
            "motif_ids": ["role:drop_1", "laser:fan", "laser:fan"],
            "laser_expression": {"color_mode": "white_hits", "geometry_family": "fan"},
            "laser_enabled": True,
            "strobe_level": 0.2,
            "intensity_multiplier": 1.0,
            "motion_multiplier": 1.0,
        },
        {
            "section_role": "drop_variation",
            "lead_family": "laser",
            "transition_intent": {"type": "bloom"},
            "motif_ids": ["role:drop_variation", "laser:fan"],
            "laser_expression": {"color_mode": "white_hits", "geometry_family": "fan"},
            "laser_enabled": True,
            "strobe_level": 0.2,
            "intensity_multiplier": 1.0,
            "motion_multiplier": 1.0,
        },
    ]

    fingerprint = cli_module._show_fingerprint(sections)

    assert fingerprint["motif_ids"].count("laser:fan") == 3
    assert fingerprint["motif_counts"]["laser:fan"] == 3
    assert fingerprint["laser_families"].count("fan") == 2
    assert fingerprint["laser_family_counts"]["fan"] == 2


def test_medium_room_preferred_lead_family_keeps_single_hero() -> None:
    lead_family, role_map = cli_module._fixture_role_map(
        section_role="drop_1",
        venue_mode="medium_room_150_400",
        laser_enabled=True,
        movers_enabled=True,
        washes_enabled=True,
        leds_enabled=True,
        preferred_lead_family="laser",
    )

    heroes = [family for family, payload in role_map.items() if payload.get("role") == "hero"]

    assert lead_family == "laser"
    assert heroes == ["laser"]


def test_medium_room_drop_variation_preferred_led_keeps_single_hero() -> None:
    lead_family, role_map = cli_module._fixture_role_map(
        section_role="drop_variation",
        venue_mode="medium_room_150_400",
        laser_enabled=True,
        movers_enabled=True,
        washes_enabled=True,
        leds_enabled=True,
        preferred_lead_family="led",
    )

    heroes = [family for family, payload in role_map.items() if payload.get("role") == "hero"]

    assert lead_family == "led"
    assert heroes == ["led"]


def test_show_planner_auto_generates_multiple_sections_without_markers() -> None:
    sections = _default_show_sections([], 324.388, track_seed="auto-track")

    assert len(sections) >= 5
    assert sections[0]["start_seconds"] == 0.0
    assert sections[-1]["end_seconds"] == 324.388
    assert all(section["end_seconds"] > section["start_seconds"] for section in sections)
    assert {section["kind"] for section in sections} & {"build", "drop", "outro"}


def test_non_drop_builds_use_build_cycle_context() -> None:
    context = _transition_context(
        previous_kind="drop",
        kind="build",
        next_kind="vocal",
        ordinal=0,
        total_of_kind=2,
    )

    assert context == "build_cycle"


def test_intro_program_avoids_sequence_and_array_laser_slots() -> None:
    sections = _default_show_sections(_markers(), 360.0, track_seed="same-song")
    intro = sections[0]
    intro_patterns = [
        intro["laser_pattern"],
        intro["laser_program"]["launch"]["pattern"],
        *[look["pattern"] for look in intro["laser_program"]["sustain"]],
        *[look["pattern"] for look in intro["laser_program"]["fills"]],
        intro["laser_program"]["release"]["pattern"],
    ]

    assert "beam_sequence_clockwise" not in intro_patterns
    assert "dual_beam" not in intro_patterns


def test_ai_assisted_mode_changes_track_pattern_plan() -> None:
    procedural_sections = _default_show_sections(
        _markers(),
        360.0,
        track_seed="same-song",
        selection_mode="procedural",
    )
    ai_sections = _default_show_sections(
        _markers(),
        360.0,
        track_seed="same-song",
        selection_mode="ai_assisted",
    )

    procedural_signature = [
        (
            section["laser_pattern"],
            section["mover_pattern"],
            section["wash_pattern"],
            section["led_pattern"],
        )
        for section in procedural_sections
    ]
    ai_signature = [
        (
            section["laser_pattern"],
            section["mover_pattern"],
            section["wash_pattern"],
            section["led_pattern"],
        )
        for section in ai_sections
    ]

    assert procedural_signature != ai_signature


def test_local_ollama_cpu_mode_uses_section_level_choices(monkeypatch) -> None:
    def _fake_ollama_section_selection(**kwargs):
        return {
            "laser": "thin_scan",
            "mover": "hold",
            "wash": "ambient",
            "led": "fade",
        }

    monkeypatch.setattr(cli_module, "_ollama_section_selection", _fake_ollama_section_selection)

    sections = _default_show_sections(
        _markers(),
        360.0,
        track_seed="same-song",
        selection_mode="local_ollama_cpu",
    )

    assert sections[0]["laser_pattern"] == "thin_scan"
    assert sections[0]["mover_pattern"] == "hold"
    assert sections[0]["wash_pattern"] == "ambient"
    assert sections[0]["led_pattern"] == "fade"


def test_local_ollama_cpu_mode_falls_back_to_procedural_when_invalid(monkeypatch) -> None:
    monkeypatch.setattr(
        cli_module,
        "_ollama_section_selection",
        lambda **kwargs: {"laser": "not_in_candidates"},
    )

    procedural_sections = _default_show_sections(
        _markers(),
        360.0,
        track_seed="same-song",
        selection_mode="procedural",
    )
    local_sections = _default_show_sections(
        _markers(),
        360.0,
        track_seed="same-song",
        selection_mode="local_ollama_cpu",
    )

    procedural_signature = [
        (
            section["laser_pattern"],
            section["mover_pattern"],
            section["wash_pattern"],
            section["led_pattern"],
        )
        for section in procedural_sections
    ]
    local_signature = [
        (
            section["laser_pattern"],
            section["mover_pattern"],
            section["wash_pattern"],
            section["led_pattern"],
        )
        for section in local_sections
    ]

    assert local_signature == procedural_signature


def test_selection_variance_changes_deterministic_plan_with_same_mode() -> None:
    locked_sections = _default_show_sections(
        _markers(),
        360.0,
        track_seed="same-song",
        selection_mode="procedural",
        selection_variance=0.0,
    )
    exploratory_sections = _default_show_sections(
        _markers(),
        360.0,
        track_seed="same-song",
        selection_mode="procedural",
        selection_variance=0.72,
    )

    locked_signature = [
        (
            section["laser_pattern"],
            section["mover_pattern"],
            section["wash_pattern"],
            section["led_pattern"],
        )
        for section in locked_sections
    ]
    exploratory_signature = [
        (
            section["laser_pattern"],
            section["mover_pattern"],
            section["wash_pattern"],
            section["led_pattern"],
        )
        for section in exploratory_sections
    ]

    assert locked_signature != exploratory_signature


def test_semantic_profile_changes_track_pattern_plan() -> None:
    base_sections = _default_show_sections(
        _markers(),
        360.0,
        track_seed="same-song",
        selection_mode="procedural",
        selection_variance=0.2,
    )
    progressive_sections = _default_show_sections(
        _markers(),
        360.0,
        track_seed="same-song",
        semantic_profile={
            "genre_hints": ["Progressive House"],
            "style_bias": {
                "progressive_patience": 0.85,
                "drop_aggression": 0.35,
                "atmosphere": 0.75,
            },
        },
        selection_mode="procedural",
        selection_variance=0.2,
    )

    base_signature = [
        (
            section["laser_pattern"],
            section["mover_pattern"],
            section["wash_pattern"],
            section["led_pattern"],
        )
        for section in base_sections
    ]
    progressive_signature = [
        (
            section["laser_pattern"],
            section["mover_pattern"],
            section["wash_pattern"],
            section["led_pattern"],
        )
        for section in progressive_sections
    ]

    assert base_signature != progressive_signature


def test_resolve_show_sections_refreshes_generated_fields_when_selection_mode_changes() -> None:
    persisted_sections = _default_show_sections(
        _markers(),
        360.0,
        track_seed="same-song",
        selection_mode="procedural",
    )
    persisted_sections[0]["label"] = "Edited Intro"
    persisted_sections[0]["start_seconds"] = 1.5

    resolved = _resolve_show_sections(
        {
            "selection_mode": "procedural",
            "show_sections": persisted_sections,
        },
        _markers(),
        360.0,
        track_seed="same-song",
        selection_mode="ai_assisted",
    )

    fallback_ai_sections = _default_show_sections(
        _markers(),
        360.0,
        track_seed="same-song",
        selection_mode="ai_assisted",
    )

    assert resolved[0]["label"] == "Edited Intro"
    assert resolved[0]["start_seconds"] == 1.5
    assert resolved[0]["laser_pattern"] == fallback_ai_sections[0]["laser_pattern"]


def test_resolve_show_sections_refreshes_generated_fields_when_selection_variance_changes() -> None:
    persisted_sections = _default_show_sections(
        _markers(),
        360.0,
        track_seed="same-song",
        selection_mode="procedural",
        selection_variance=0.0,
    )

    resolved = _resolve_show_sections(
        {
            "selection_mode": "procedural",
            "selection_variance": 0.0,
            "show_sections": persisted_sections,
        },
        _markers(),
        360.0,
        track_seed="same-song",
        selection_mode="procedural",
        selection_variance=0.72,
    )

    exploratory_sections = _default_show_sections(
        _markers(),
        360.0,
        track_seed="same-song",
        selection_mode="procedural",
        selection_variance=0.72,
    )

    resolved_signature = [
        (
            section["laser_pattern"],
            section["mover_pattern"],
            section["wash_pattern"],
            section["led_pattern"],
        )
        for section in resolved
    ]
    exploratory_signature = [
        (
            section["laser_pattern"],
            section["mover_pattern"],
            section["wash_pattern"],
            section["led_pattern"],
        )
        for section in exploratory_sections
    ]

    assert resolved_signature == exploratory_signature


def test_resolve_show_sections_refreshes_generated_fields_when_venue_mode_changes() -> None:
    persisted_sections = _default_show_sections(
        _markers(),
        360.0,
        track_seed="same-song",
        venue_mode="small_room_50_100",
    )

    resolved = _resolve_show_sections(
        {
            "selection_mode": "procedural",
            "selection_variance": 0.0,
            "venue_mode": "small_room_50_100",
            "show_sections": persisted_sections,
        },
        _markers(),
        360.0,
        track_seed="same-song",
        venue_mode="medium_room_150_400",
    )

    assert resolved[0]["venue_mode"] == "medium_room_150_400"
    assert resolved[0]["motion_multiplier"] > persisted_sections[0]["motion_multiplier"]
