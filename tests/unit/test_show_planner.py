from photonic_synesthesia.ui.cli import _LASER_PATTERN_POOLS, _default_show_sections


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
    assert laser_program["phrase_role"] in {"drop_launch", "drop_variation", "build_riser", "breakdown_release", "intro_set", "outro_release"}
    assert laser_program["zone_policy"] in {"overhead_only", "mixed_air", "crowd_punctuate", "overhead_bias"}
    assert laser_program["launch"]["pattern"]
    assert laser_program["release"]["pattern"]
    assert len(laser_program["sustain"]) >= 1
    assert len(laser_program["fills"]) >= 1
    assert all(look["geometry_family"] for look in laser_program["sustain"])
