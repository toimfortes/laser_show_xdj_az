"""Coordinated per-section pattern selection for the showplan facade."""

from __future__ import annotations

from typing import Any, Callable

from photonic_synesthesia.showplan._patterns import (
    normalize_selection_mode as _default_normalize_selection_mode,
    normalize_selection_variance as _default_normalize_selection_variance,
    ollama_section_selection as _default_ollama_section_selection,
    pattern_candidates as _default_pattern_candidates,
    select_pattern as _default_select_pattern,
)


def select_section_patterns(
    *,
    kind: str,
    context: str,
    profile: dict[str, Any],
    track_seed: str,
    marker_name: str,
    ordinal: int,
    previous_patterns: dict[str, str | None],
    pattern_history: dict[str, list[str]] | None,
    usage_count_by_family: dict[str, dict[str, int]] | None,
    semantic_profile: dict[str, Any] | None,
    selection_mode: str,
    energy_scale: float,
    selection_variance: float,
    normalize_selection_mode: Callable[[str | None], str] | None = None,
    normalize_selection_variance: Callable[[Any | None], float] | None = None,
    pattern_candidates_fn: Callable[..., list[str]] | None = None,
    ollama_section_selection_fn: Callable[..., dict[str, str] | None] | None = None,
    select_pattern_fn: Callable[..., str] | None = None,
) -> dict[str, str]:
    """Pick one pattern per family for a section, optionally coordinated via Ollama.

    Callable dependencies fall back to the internal `_patterns` leaf, which is a
    duplicated-as-default copy of the CLI's selection primitives. Callers that
    need the CLI's live behaviour should inject the CLI-owned helpers.
    """
    _normalize_selection_mode = normalize_selection_mode or _default_normalize_selection_mode
    _normalize_selection_variance = normalize_selection_variance or _default_normalize_selection_variance
    _pattern_candidates = pattern_candidates_fn or _default_pattern_candidates
    _select_pattern = select_pattern_fn or _default_select_pattern
    _ollama_section_selection = ollama_section_selection_fn or _default_ollama_section_selection

    normalized_mode = _normalize_selection_mode(selection_mode)
    selection_variance = _normalize_selection_variance(selection_variance)
    resolved: dict[str, str] = {}
    ollama_choices: dict[str, str] | None = None
    family_candidates = {
        family: set(_pattern_candidates(family=family, kind=kind, context=context, profile=profile))
        for family in ("laser", "mover", "wash", "led")
    }
    if normalized_mode == "local_ollama_cpu":
        ollama_choices = _ollama_section_selection(
            kind=kind,
            context=context,
            profile=profile,
            track_seed=track_seed,
            marker_name=marker_name,
            ordinal=ordinal,
            energy_scale=energy_scale,
            previous_patterns=previous_patterns,
            pattern_history=pattern_history,
            usage_count_by_family=usage_count_by_family,
            semantic_profile=semantic_profile,
            selection_variance=selection_variance,
        )
    for family in ("laser", "mover", "wash", "led"):
        if (
            ollama_choices
            and ollama_choices.get(family)
            and ollama_choices[family] in family_candidates[family]
        ):
            resolved[family] = ollama_choices[family]
            continue
        fallback_mode = "procedural" if normalized_mode == "local_ollama_cpu" else normalized_mode
        resolved[family] = _select_pattern(
            family=family,
            kind=kind,
            context=context,
            profile=profile,
            track_seed=track_seed,
            marker_name=marker_name,
            ordinal=ordinal,
            previous_pattern=previous_patterns.get(family),
            recent_patterns=(pattern_history or {}).get(family, [])[-4:],
            usage_count_by_pattern=(usage_count_by_family or {}).get(family, {}),
            semantic_profile=semantic_profile,
            selection_mode=fallback_mode,
            energy_scale=energy_scale,
            selection_variance=selection_variance,
        )
    return resolved
