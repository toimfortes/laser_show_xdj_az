"""Pure section mutation helpers for runtime playback context."""

from __future__ import annotations

from typing import Any

from photonic_synesthesia.platform.runtime_context_normalization import clamp


def set_family_intensity(section: dict[str, Any], family: str, scale: float) -> None:
    fixture_role_map = section.get("fixture_role_map")
    if isinstance(fixture_role_map, dict) and isinstance(fixture_role_map.get(family), dict):
        role_meta = fixture_role_map[family]
        role_meta["intensity_ceiling"] = round(
            clamp(float(role_meta.get("intensity_ceiling") or 0.0) * scale, 0.0, 1.5),
            3,
        )
    cue_recipe = section.get("cue_recipe")
    if not isinstance(cue_recipe, dict):
        return
    cue_map = cue_recipe.get("fixture_role_map")
    if isinstance(cue_map, dict) and isinstance(cue_map.get(family), dict):
        role_meta = cue_map[family]
        role_meta["intensity_ceiling"] = round(
            clamp(float(role_meta.get("intensity_ceiling") or 0.0) * scale, 0.0, 1.5),
            3,
        )
    families = cue_recipe.get("families")
    if isinstance(families, dict) and isinstance(families.get(family), dict):
        family_payload = families[family]
        family_payload["intensity_ceiling"] = round(
            clamp(float(family_payload.get("intensity_ceiling") or 0.0) * scale, 0.0, 1.5),
            3,
        )


def sync_cue_family_family_id(section: dict[str, Any], family: str) -> None:
    cue_family_id = str(section.get("cue_family_id") or "")
    if "::" in cue_family_id:
        prefix = cue_family_id.rsplit("::", 1)[0]
        cue_family_id = f"{prefix}::{family}"
        section["cue_family_id"] = cue_family_id
    cue_recipe = section.get("cue_recipe")
    if isinstance(cue_recipe, dict):
        cue_recipe["lead_family"] = family
        if "::" in str(cue_recipe.get("cue_family_id") or ""):
            prefix = str(cue_recipe["cue_family_id"]).rsplit("::", 1)[0]
            cue_recipe["cue_family_id"] = f"{prefix}::{family}"
        recipe_bundle = cue_recipe.get("recipe_bundle")
        if isinstance(recipe_bundle, dict):
            recipe_bundle["lead_family"] = family
            if "::" in str(recipe_bundle.get("cue_family_id") or ""):
                prefix = str(recipe_bundle["cue_family_id"]).rsplit("::", 1)[0]
                recipe_bundle["cue_family_id"] = f"{prefix}::{family}"


def promote_family_to_hero(section: dict[str, Any], family: str) -> None:
    section["lead_family"] = family
    fixture_role_map = section.get("fixture_role_map")
    if isinstance(fixture_role_map, dict):
        for name, payload in fixture_role_map.items():
            if not isinstance(payload, dict):
                continue
            if name == family:
                payload["role"] = "hero"
            elif payload.get("role") == "hero":
                payload["role"] = "support"
    cue_recipe = section.get("cue_recipe")
    if isinstance(cue_recipe, dict):
        cue_recipe["lead_family"] = family
        cue_map = cue_recipe.get("fixture_role_map")
        if isinstance(cue_map, dict):
            for name, payload in cue_map.items():
                if not isinstance(payload, dict):
                    continue
                if name == family:
                    payload["role"] = "hero"
                elif payload.get("role") == "hero":
                    payload["role"] = "support"
    sync_cue_family_family_id(section, family)


def update_operator_override(section: dict[str, Any], key: str, value: Any) -> None:
    section.setdefault("operator_overrides", {})
    if isinstance(section["operator_overrides"], dict):
        section["operator_overrides"][key] = value
    cue_recipe = section.get("cue_recipe")
    if isinstance(cue_recipe, dict):
        cue_recipe.setdefault("operator_overrides", {})
        if isinstance(cue_recipe["operator_overrides"], dict):
            cue_recipe["operator_overrides"][key] = value


def apply_nested_change(section: dict[str, Any], dotted_key: str, value: Any) -> None:
    parts = dotted_key.split(".")
    target: Any = section
    for index, part in enumerate(parts[:-1]):
        next_part = parts[index + 1]
        expect_list = next_part.isdigit()
        if isinstance(target, list):
            if not part.isdigit():
                return
            item_index = int(part)
            while len(target) <= item_index:
                target.append([] if expect_list else {})
            current = target[item_index]
            if expect_list and not isinstance(current, list):
                current = []
                target[item_index] = current
            elif not expect_list and not isinstance(current, dict):
                current = {}
                target[item_index] = current
            target = current
            continue

        if not isinstance(target, dict):
            return

        current = target.get(part)
        if expect_list:
            if not isinstance(current, list):
                current = []
                target[part] = current
        else:
            if not isinstance(current, dict):
                current = {}
                target[part] = current
        target = current
    leaf = parts[-1]
    if leaf in {
        "content_family",
        "geometry_family",
        "color_mode",
        "target_bias",
        "target_strategy",
        "blanking_strategy",
        "color_strategy",
        "transition_role",
        "label",
        "intensity_curve",
        "pattern",
        "zone_policy",
        "phrase_role",
        "id",
    }:
        if isinstance(target, dict):
            target[leaf] = str(value)
    elif leaf in {"mirror"}:
        if isinstance(target, dict):
            target[leaf] = bool(value)
    elif leaf in {
        "x_amplitude",
        "y_amplitude",
        "rotation_rate",
        "sweep_density",
        "color_cycle_rate",
        "white_accent",
        "crowd_bias",
        "ceiling_bias",
        "launch_intensity",
        "sustain_intensity",
        "release_intensity",
        "sustain_motion",
        "density",
        "motion",
        "emphasis",
    }:
        try:
            if isinstance(target, dict):
                target[leaf] = float(value)
        except (TypeError, ValueError):
            return
    elif leaf in {
        "launch_bars",
        "sustain_bars",
        "release_bars",
        "normalize_after_bars",
        "bars",
        "fill_trigger_every_bars",
    }:
        try:
            if isinstance(target, dict):
                target[leaf] = int(value)
        except (TypeError, ValueError):
            return
    elif leaf == "variation_plan":
        if not isinstance(target, dict):
            return
        if isinstance(value, list):
            target[leaf] = [str(item) for item in value]
        else:
            target[leaf] = [line.strip() for line in str(value).splitlines() if line.strip()]
