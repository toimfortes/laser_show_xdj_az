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


# --- Task 1 professional rollout: PlaybackContext architecture --------------

import copy
import json
import os
from pathlib import Path
import tempfile
from unittest import mock

from photonic_synesthesia.platform.runtime_context import PlaybackContext


def _ctx(**kwargs):
    defaults = dict(
        file_path="demo.wav",
        file_name="demo.wav",
        duration_seconds=60.0,
    )
    defaults.update(kwargs)
    return PlaybackContext(**defaults)


def test_playback_context_seeds_hashes_in_post_init() -> None:
    """Cycle-3 panel 3C-N3: __post_init__ must seed `_authored_hash` and
    `_flags_hash` so the first mutation doesn't bump
    `_timeline_flag_revision` (which would clear the trigger ledger)."""
    ctx = _ctx(show_sections=[
        {"id": "sec-0", "section_role": "intro", "start_seconds": 0.0, "end_seconds": 30.0},
    ])
    assert ctx._authored_hash != ""
    assert ctx._flags_hash != ""
    # First snapshot must NOT trigger a revision bump.
    initial_rev = ctx._timeline_flag_revision
    ctx.snapshot()
    assert ctx._timeline_flag_revision == initial_rev


def test_snapshot_returns_superset_of_shipped_fields() -> None:
    """Cycle-3 panel 3C-N2: snapshot must include shipped fields PLUS new
    authored-cache fields PLUS live overlay."""
    ctx = _ctx()
    snap = ctx.snapshot()
    # Sample of shipped fields.
    for key in [
        "available", "session_id", "file_name", "track_title", "audio_url",
        "show_plan_path", "waveform", "structure_markers", "selection_mode",
        "metadata_confidence", "operator_intents", "playhead_seconds",
        "transport_revision",
    ]:
        assert key in snap, f"missing shipped field: {key}"
    # New authored-cache fields.
    for key in [
        "show_sections", "timeline_flags", "staged_look",
        "operator_workspace_banks", "timeline_flag_revision", "authored_hash",
    ]:
        assert key in snap, f"missing authored field: {key}"
    # Live overlay.
    assert "active_scene_id" in snap


def test_snapshot_active_scene_id_follows_playhead() -> None:
    """Cycle-1 panel UF-7: active_scene_id MUST be derived per-call from
    the live playhead, NOT cached against an authored hash."""
    ctx = _ctx(show_sections=[
        {"id": "sec-0", "section_role": "intro", "start_seconds": 0.0, "end_seconds": 30.0},
        {"id": "sec-1", "section_role": "drop_1", "start_seconds": 30.0, "end_seconds": 60.0},
    ])
    assert ctx.snapshot()["active_scene_id"] == "sec-0"
    ctx.update_transport(playhead_seconds=45.0, playing=True, finished=False, realtime=True, speed=1.0)
    assert ctx.snapshot()["active_scene_id"] == "sec-1"


def test_snapshot_public_api_deep_copies() -> None:
    """Cycle-2 panel NC-8 + cycle-3 panel 3C-N2: public snapshot()
    deep-copies so callers can mutate the result without poisoning the
    cache."""
    ctx = _ctx(show_sections=[{"id": "sec-0", "start_seconds": 0.0, "end_seconds": 60.0}])
    snap1 = ctx.snapshot()
    snap1["show_sections"].append({"rogue": True})
    snap2 = ctx.snapshot()
    assert len(snap2["show_sections"]) == 1, "public snapshot leak — cache poisoned"


def test_snapshot_uses_cached_media_availability_not_live_filesystem_probes() -> None:
    """Playback snapshots run on the 50 Hz graph path. They must not hit
    `Path.is_file()` on every call under the shared context lock."""
    ctx = _ctx(
        file_path="/tmp/audio.wav",
        ilda_export_path="/tmp/export.ild",
    )
    assert ctx._audio_available is False
    assert ctx._ilda_export_available is False

    with mock.patch.object(Path, "is_file", side_effect=AssertionError("snapshot must not probe disk")):
        snap = ctx.snapshot()

    assert snap["audio_available"] is False
    assert snap["ilda_export_available"] is False


def test_set_staged_look_via_recompute_does_not_clear_trigger_ledger() -> None:
    """Cycle-2 panel NC-3 split: changing `staged_look` bumps
    `_authored_hash` (cache invalidation) but NOT `_flags_hash`
    (trigger-ledger invalidation), because timeline_flags didn't change."""
    ctx = _ctx(show_sections=[{"id": "sec-0", "start_seconds": 0.0, "end_seconds": 60.0}])
    initial_rev = ctx._timeline_flag_revision
    initial_authored = ctx._authored_hash

    ctx.staged_look = {"section_id": "sec-0", "cue_recipe": {}, "laser_program": {}}
    with ctx._lock:
        ctx._recompute_authored_hash_locked()

    assert ctx._authored_hash != initial_authored, "authored_hash should bump on staged_look change"
    assert ctx._timeline_flag_revision == initial_rev, "timeline_flag_revision should NOT bump"


def test_replace_show_sections_publishes_authored_state() -> None:
    """Task 1 Step 13 acceptance: replace_show_sections() returns a
    snapshot reflecting the new sections immediately."""
    ctx = _ctx()
    new_sections = [
        {"id": "sec-2", "start_seconds": 16.0, "end_seconds": 32.0, "tags": ["role:drop"]},
    ]
    snap = ctx.replace_show_sections(new_sections)
    assert snap["show_sections"][0]["id"] == "sec-2"
    # Snapshot's authored cache reflects the update.
    assert snap["authored_hash"] == ctx._authored_hash


def test_persisted_timeline_flags_hint_is_a_real_slots_field() -> None:
    """Cycle-2 panel NC-1: PlaybackContext is @dataclass(slots=True);
    the hint MUST be a declared field, otherwise assignment raises
    AttributeError at runtime."""
    ctx = _ctx()
    ctx._persisted_timeline_flags_hint = [{"id": "test", "at_seconds": 0.0}]
    assert ctx._persisted_timeline_flags_hint is not None
    # Used by replace_show_sections (or bind_track_metadata).
    ctx.replace_show_sections([{"id": "x", "start_seconds": 0.0, "end_seconds": 60.0}])
    # Hint cleared after use.
    assert ctx._persisted_timeline_flags_hint is None


def test_load_show_plan_migrates_v1_to_v2() -> None:
    """Cycle-1 panel UF-1, UF-2: v1→v2 migration with literal version gate
    and `_schema_version` key. Must work without going through save_show_plan
    (which would stamp the new schema and never exercise the migration)."""
    from photonic_synesthesia.integrations.show_plans import (
        _SCHEMA_KEY, load_show_plan, show_plan_path,
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["XDG_DATA_HOME"] = tmpdir
        try:
            plan = show_plan_path("legacy-track")
            plan.parent.mkdir(parents=True, exist_ok=True)
            # Raw v1 JSON: no _schema_version key.
            plan.write_text(json.dumps({
                "show_sections": [{"id": "sec-0", "start_seconds": 0.0, "end_seconds": 10.0}],
            }), encoding="utf-8")

            loaded = load_show_plan("legacy-track")
            assert loaded is not None
            assert loaded[_SCHEMA_KEY] == 2
            assert loaded["timeline_flags"] == []
            assert loaded["staged_look"] is None
            assert loaded["operator_intents"] == []
        finally:
            os.environ.pop("XDG_DATA_HOME", None)


def test_load_show_plan_returns_none_on_missing() -> None:
    """Cycle-1 panel UF-1: Optional[dict] return contract preserved."""
    from photonic_synesthesia.integrations.show_plans import load_show_plan
    assert load_show_plan("never-saved-key") is None
