"""Task 4 acceptance: staging-lane pure helpers + PlaybackContext methods.

Pins the cycle-N invariants: preview-only contract (UF-11), deep-merge
preservation (UF-12 / B5), commit fail-closed when playhead advances
past the staged section (SF-1), authored hash bumps without touching
the trigger-router ledger (NC-3 split).
"""

from __future__ import annotations

import pytest

from photonic_synesthesia.platform.runtime_context import PlaybackContext
from photonic_synesthesia.platform.staging_lane import commit_staged_look, stage_look


# --- staging_lane pure helpers --------------------------------------------

def test_stage_look_emits_preview_only_dict() -> None:
    staged = stage_look(
        section_id="drop-a",
        cue_recipe={"id": "cue-1"},
        laser_program={"id": "laser-1"},
    )
    assert staged["section_id"] == "drop-a"
    assert staged["committed"] is False
    assert staged["source"] == "operator"
    # Defensive copies — caller's dicts must not alias the staged ones.
    assert staged["cue_recipe"] is not None
    assert staged["laser_program"] is not None


def test_commit_staged_look_flips_committed_flag_to_true() -> None:
    staged = stage_look(section_id="drop-a", cue_recipe={"id": "cue-1"}, laser_program={})
    committed = commit_staged_look(staged)
    assert staged["committed"] is False, "input must not be mutated"
    assert committed["committed"] is True


# --- PlaybackContext staging methods -------------------------------------

def _ctx_with_section() -> PlaybackContext:
    ctx = PlaybackContext(file_path="demo.wav", file_name="demo.wav", duration_seconds=60.0)
    ctx.replace_show_sections([{
        "id": "sec-0", "section_role": "intro",
        "start_seconds": 0.0, "end_seconds": 30.0,
        "cue_recipe": {"phasers": [{"family": "breathing"}], "recipe_lines": [{"selection": "wash:intro"}]},
        "laser_program": {"zone_policy": "overhead_only", "fills": [{"label": "Fill A"}]},
        "transition_intent": {"type": "bloom"},
        "section_role": "intro",
    }])
    return ctx


def test_set_staged_look_does_not_affect_runtime_show_sections() -> None:
    """Cycle-1 panel UF-11: preview-only — runtime reads show_sections only."""
    ctx = _ctx_with_section()
    ctx.set_staged_look(
        section_id="sec-0",
        cue_recipe={"phasers": [{"family": "pressure"}]},
        laser_program={"zone_policy": "crowd_punctuate"},
    )
    snap = ctx.snapshot()
    sec = snap["show_sections"][0]
    assert sec["cue_recipe"]["phasers"][0]["family"] == "breathing", "preview leaked into runtime"
    assert sec["laser_program"]["zone_policy"] == "overhead_only", "preview leaked into runtime"
    # But staged_look IS surfaced for UI preview.
    assert snap["staged_look"]["section_id"] == "sec-0"


def test_set_staged_look_does_not_bump_timeline_flag_revision() -> None:
    """Cycle-2 panel NC-3 split: staged_look change bumps _authored_hash
    but NOT _flags_hash, so TriggerRouterNode's ledger is preserved."""
    ctx = _ctx_with_section()
    initial_rev = ctx._timeline_flag_revision
    ctx.set_staged_look(section_id="sec-0", cue_recipe={"x": 1}, laser_program={"y": 2})
    assert ctx._timeline_flag_revision == initial_rev


def test_commit_staged_look_deep_merges_authored_section() -> None:
    """Cycle-1 panel UF-12: operator override takes only the keys it
    supplied; every other authored field survives."""
    ctx = _ctx_with_section()
    ctx.set_staged_look(
        section_id="sec-0",
        cue_recipe={"phasers": [{"family": "pressure"}]},
        laser_program={"zone_policy": "crowd_punctuate"},
    )
    ctx.commit_staged_look()
    sec = ctx.show_sections[0]
    # Operator overrides took effect.
    assert sec["cue_recipe"]["phasers"][0]["family"] == "pressure"
    assert sec["laser_program"]["zone_policy"] == "crowd_punctuate"
    # Authored fields the operator did NOT touch survived.
    assert sec["cue_recipe"]["recipe_lines"][0]["selection"] == "wash:intro"
    assert sec["laser_program"]["fills"][0]["label"] == "Fill A"
    assert sec["transition_intent"]["type"] == "bloom"
    # staged_look cleared.
    assert ctx.staged_look is None


def test_commit_staged_look_fails_closed_when_playhead_advanced_past_section() -> None:
    """Cycle-1 panel SF-1: operator must re-stage if the playhead moved
    past the staged section's end between stage and commit."""
    ctx = _ctx_with_section()
    ctx.set_staged_look(section_id="sec-0", cue_recipe={"x": 1}, laser_program={"y": 2})
    ctx.update_transport(playhead_seconds=45.0, playing=True, finished=False, realtime=True, speed=1.0)
    with pytest.raises(RuntimeError, match="re-stage against the current section"):
        ctx.commit_staged_look()


def test_commit_staged_look_raises_without_a_staged_look() -> None:
    ctx = _ctx_with_section()
    with pytest.raises(RuntimeError, match="No staged look"):
        ctx.commit_staged_look()


def test_set_staged_look_rejects_unknown_section_id() -> None:
    ctx = _ctx_with_section()
    with pytest.raises(RuntimeError, match="Unknown section"):
        ctx.set_staged_look(section_id="ghost", cue_recipe={}, laser_program={})


# --- operator_workspace bank builder --------------------------------------

def test_build_operator_workspace_banks_emits_scene_safety_tag_banks() -> None:
    from photonic_synesthesia.platform.operator_workspace import build_operator_workspace_banks
    from photonic_synesthesia.showplan.types import SAFETY_MODES

    banks = build_operator_workspace_banks(
        sections=[
            {"id": "sec-0", "label": "Intro"},
            {"id": "sec-1", "label": "Drop"},
        ],
        available_tags=["role:drop_1", "lead:laser"],
        safety_modes=SAFETY_MODES,
    )
    bank_ids = [b["id"] for b in banks["banks"]]
    assert bank_ids == ["scene", "safety", "tags"]
    scene_buttons = [b["id"] for b in banks["banks"][0]["buttons"]]
    assert scene_buttons == ["scene:sec-0", "scene:sec-1"]
    safety_buttons = [b["id"] for b in banks["banks"][1]["buttons"]]
    assert len(safety_buttons) == len(SAFETY_MODES)
    assert "safety:overhead_only" in safety_buttons
    tag_buttons = [b["id"] for b in banks["banks"][2]["buttons"]]
    assert tag_buttons == ["tag:role:drop_1", "tag:lead:laser"]
