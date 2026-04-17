import photonic_synesthesia.ui.cli as cli_module
from photonic_synesthesia.ui.cli import (
    _LASER_PATTERN_POOLS,
    _default_show_sections,
    _resolve_show_sections,
    _transition_context,
)


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
    assert cue_recipe["version"] == 1
    assert cue_recipe["intent"] == laser_program["phrase_role"]
    assert cue_recipe["stage"] == "drop"
    assert cue_recipe["timing_master"]
    assert cue_recipe["families"]["laser"]["pattern"] == drop["laser_pattern"]
    assert cue_recipe["families"]["laser"]["zone_policy"] == laser_program["zone_policy"]
    assert cue_recipe["families"]["mover"]["group"]


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
