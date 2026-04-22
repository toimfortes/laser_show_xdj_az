from photonic_synesthesia.platform import (
    BindingStatus as PlatformBindingStatus,
    LiveDeckFact as PlatformLiveDeckFact,
    LiveDeckSnapshot as PlatformLiveDeckSnapshot,
    PlaybackContext,
)
from photonic_synesthesia.platform.live_deck_binding import (
    LiveDeckAutoBindEngine,
    resolve_track_identity,
)
from photonic_synesthesia.platform.live_deck_models import (
    BindingStatus,
    LiveDeckFact,
    LiveDeckSnapshot,
)


def test_live_deck_fact_allows_missing_nonessential_metadata() -> None:
    fact = LiveDeckFact(
        player_number=3,
        master=True,
        on_air=True,
        updated_at=1713660000.0,
    )

    assert fact.player_number == 3
    assert fact.playhead_seconds is None
    assert fact.speed is None
    assert fact.playing is None
    assert fact.track_title is None
    assert fact.track_artist is None
    assert fact.duration_seconds is None
    assert fact.bpm is None
    assert fact.track_id is None
    assert fact.source_type is None
    assert fact.master is True
    assert fact.on_air is True


def test_binding_status_exposes_reason_and_confidence() -> None:
    status = BindingStatus(
        state="bound",
        reason="authoritative deck resolved",
        authority_player=3,
        resolved_track_key="ARTBAT|Age of Love",
        match_confidence=1.0,
        last_update_at=1713660000.0,
    )

    assert status.state == "bound"
    assert status.authority_player == 3
    assert status.match_confidence == 1.0


def test_non_bound_binding_status_can_be_created_cleanly() -> None:
    status = BindingStatus(
        state="conflict",
        reason="multiple decks matched the same track",
        authority_player=None,
    )

    assert status.state == "conflict"
    assert status.resolved_track_key is None
    assert status.match_confidence is None
    assert status.last_update_at is None


def test_platform_reexports_live_deck_models() -> None:
    assert PlatformLiveDeckFact is LiveDeckFact
    assert PlatformLiveDeckSnapshot is LiveDeckSnapshot
    assert PlatformBindingStatus is BindingStatus


def test_live_deck_snapshot_wraps_decks() -> None:
    fact = LiveDeckFact(
        player_number=3,
        master=True,
        on_air=True,
        updated_at=1713660000.0,
    )
    snapshot = LiveDeckSnapshot(decks=[fact])

    assert snapshot.decks[0].player_number == 3
    assert snapshot.decks[0].track_id is None


def test_live_deck_snapshot_defaults_to_empty() -> None:
    snapshot = LiveDeckSnapshot()

    assert snapshot.decks == []


def test_engine_selects_single_on_air_master_deck() -> None:
    engine = LiveDeckAutoBindEngine(stale_after_seconds=0.5)
    status = engine.evaluate(
        [
            LiveDeckFact(player_number=1, playing=True, on_air=False, master=False, updated_at=100.0),
            LiveDeckFact(player_number=3, playing=True, on_air=True, master=True, updated_at=100.0),
        ],
        now=100.1,
    )

    assert status.state == "bound"
    assert status.authority_player == 3


def test_engine_reports_conflict_for_multiple_on_air_master_decks() -> None:
    engine = LiveDeckAutoBindEngine(stale_after_seconds=0.5)
    status = engine.evaluate(
        [
            LiveDeckFact(player_number=1, on_air=True, master=True, updated_at=100.0),
            LiveDeckFact(player_number=2, on_air=True, master=True, updated_at=100.0),
        ],
        now=100.1,
    )

    assert status.state == "conflict"
    assert status.authority_player is None


def test_engine_reports_stale_when_last_authority_expires() -> None:
    engine = LiveDeckAutoBindEngine(stale_after_seconds=0.5)
    engine.evaluate(
        [LiveDeckFact(player_number=3, on_air=True, master=True, updated_at=100.0)],
        now=100.1,
    )
    status = engine.evaluate([], now=100.8)

    assert status.state == "stale"
    assert status.authority_player == 3


def test_engine_reports_stale_for_current_authority_that_is_already_stale() -> None:
    engine = LiveDeckAutoBindEngine(stale_after_seconds=0.5)
    status = engine.evaluate(
        [LiveDeckFact(player_number=3, on_air=True, master=True, updated_at=100.0)],
        now=100.6,
    )

    assert status.state == "stale"
    assert status.authority_player == 3


def test_engine_reports_unbound_when_authority_never_seen() -> None:
    engine = LiveDeckAutoBindEngine(stale_after_seconds=0.5)

    status = engine.evaluate([], now=100.0)

    assert status.state == "unbound"
    assert status.authority_player is None


def test_engine_reports_unbound_when_authority_disappears_before_timeout() -> None:
    engine = LiveDeckAutoBindEngine(stale_after_seconds=0.5)
    engine.evaluate(
        [LiveDeckFact(player_number=3, on_air=True, master=True, updated_at=100.0)],
        now=100.1,
    )

    status = engine.evaluate([], now=100.4)

    assert status.state == "unbound"
    assert status.authority_player is None


def test_engine_conflict_clears_cached_authority_and_fails_closed() -> None:
    engine = LiveDeckAutoBindEngine(stale_after_seconds=0.5)

    first = engine.evaluate(
        [LiveDeckFact(player_number=3, on_air=True, master=True, updated_at=100.0)],
        now=100.1,
    )
    second = engine.evaluate(
        [
            LiveDeckFact(player_number=3, on_air=True, master=True, updated_at=100.2),
            LiveDeckFact(player_number=4, on_air=True, master=True, updated_at=100.2),
        ],
        now=100.2,
    )
    third = engine.evaluate([], now=100.8)

    assert first.state == "bound"
    assert second.state == "conflict"
    assert third.state == "unbound"
    assert third.authority_player is None


def test_engine_keeps_fresher_authority_when_older_snapshot_arrives() -> None:
    engine = LiveDeckAutoBindEngine(stale_after_seconds=0.5)

    first = engine.evaluate(
        [LiveDeckFact(player_number=3, on_air=True, master=True, updated_at=100.2)],
        now=100.25,
    )
    second = engine.evaluate(
        [LiveDeckFact(player_number=3, on_air=True, master=True, updated_at=100.0)],
        now=100.3,
    )
    third = engine.evaluate([], now=100.8)

    assert first.state == "bound"
    assert first.last_update_at == 100.2
    assert second.state == "bound"
    assert second.authority_player == 3
    assert second.last_update_at == 100.2
    assert third.state == "stale"
    assert third.authority_player == 3
    assert third.last_update_at == 100.2


def test_engine_switches_to_new_player_even_when_update_is_older() -> None:
    engine = LiveDeckAutoBindEngine(stale_after_seconds=0.5)

    first = engine.evaluate(
        [LiveDeckFact(player_number=3, on_air=True, master=True, updated_at=100.3)],
        now=100.35,
    )
    second = engine.evaluate(
        [LiveDeckFact(player_number=4, on_air=True, master=True, updated_at=100.0)],
        now=100.3,
    )

    assert first.state == "bound"
    assert first.authority_player == 3
    assert first.last_update_at == 100.3
    assert second.state == "bound"
    assert second.authority_player == 4
    assert second.last_update_at == 100.0


def test_resolve_track_identity_prefers_exact_title_artist_duration() -> None:
    payload = resolve_track_identity(
        title="Age of Love",
        artist="ARTBAT / Pete Tong",
        duration_seconds=445.4,
        candidates=[
            {
                "track_key": "ARTBAT / Pete Tong|Age of Love",
                "track_title": "Age of Love",
                "track_artist": "ARTBAT / Pete Tong",
                "duration_seconds": 445.4,
            },
            {
                "track_key": "Another Artist|Age of Love",
                "track_title": "Age of Love",
                "track_artist": "Another Artist",
                "duration_seconds": 445.4,
            },
        ],
    )

    assert payload["state"] == "bound"
    assert payload["resolved_track_key"] == "ARTBAT / Pete Tong|Age of Love"


def test_resolve_track_identity_reports_ambiguous_for_multiple_exact_candidates() -> None:
    payload = resolve_track_identity(
        title="Age of Love",
        artist="ARTBAT / Pete Tong",
        duration_seconds=445.4,
        candidates=[
            {
                "track_key": "ARTBAT / Pete Tong|Age of Love#1",
                "track_title": "Age of Love",
                "track_artist": "ARTBAT / Pete Tong",
                "duration_seconds": 445.4,
            },
            {
                "track_key": "ARTBAT / Pete Tong|Age of Love#2",
                "track_title": "Age of Love",
                "track_artist": "ARTBAT / Pete Tong",
                "duration_seconds": 445.4,
            },
        ],
    )

    assert payload["state"] == "ambiguous"
    assert payload["resolved_track_key"] == ""


def test_resolve_track_identity_reports_unbound_when_no_exact_candidate_matches() -> None:
    payload = resolve_track_identity(
        title="Age of Love",
        artist="ARTBAT / Pete Tong",
        duration_seconds=445.4,
        candidates=[
            {
                "track_key": "ARTBAT / Pete Tong|Age of Love",
                "track_title": "Age of Love",
                "track_artist": "ARTBAT / Pete Tong",
                "duration_seconds": 447.0,
            },
            {
                "track_key": "Another Artist|Age of Love",
                "track_title": "Age of Love",
                "track_artist": "Another Artist",
                "duration_seconds": 445.4,
            },
        ],
    )

    assert payload["state"] == "unbound"
    assert payload["resolved_track_key"] == ""


def test_resolve_track_identity_accepts_small_duration_rounding_delta() -> None:
    payload = resolve_track_identity(
        title="Another Track",
        artist="Yotto",
        duration_seconds=390.499,
        candidates=[
            {
                "track_key": "Yotto|Another Track",
                "track_title": "Another Track",
                "track_artist": "Yotto",
                "duration_seconds": 390.5,
            }
        ],
    )

    assert payload["state"] == "bound"
    assert payload["resolved_track_key"] == "Yotto|Another Track"


def test_resolve_track_identity_does_not_bind_without_usable_track_key() -> None:
    payload = resolve_track_identity(
        title="Age of Love",
        artist="ARTBAT / Pete Tong",
        duration_seconds=445.4,
        candidates=[
            {
                "track_key": "",
                "track_title": "Age of Love",
                "track_artist": "ARTBAT / Pete Tong",
                "duration_seconds": 445.4,
            }
        ],
    )

    assert payload["state"] == "unbound"
    assert payload["resolved_track_key"] == ""


def test_resolve_track_identity_ignores_malformed_duration_rows() -> None:
    payload = resolve_track_identity(
        title="Age of Love",
        artist="ARTBAT / Pete Tong",
        duration_seconds=445.4,
        candidates=[
            {
                "track_key": "bad-duration",
                "track_title": "Age of Love",
                "track_artist": "ARTBAT / Pete Tong",
                "duration_seconds": "not-a-number",
            }
        ],
    )

    assert payload["state"] == "unbound"
    assert payload["resolved_track_key"] == ""


def test_resolve_track_identity_ignores_blank_duration_rows() -> None:
    payload = resolve_track_identity(
        title="Unknown Intro",
        artist="Test Artist",
        duration_seconds=0.0,
        candidates=[
            {
                "track_key": "Test Artist|Unknown Intro",
                "track_title": "Unknown Intro",
                "track_artist": "Test Artist",
                "duration_seconds": "",
            }
        ],
    )

    assert payload["state"] == "unbound"
    assert payload["resolved_track_key"] == ""


def test_resolve_track_identity_ignores_non_finite_duration_rows() -> None:
    payload = resolve_track_identity(
        title="Unknown Intro",
        artist="Test Artist",
        duration_seconds=float("inf"),
        candidates=[
            {
                "track_key": "Test Artist|Unknown Intro",
                "track_title": "Unknown Intro",
                "track_artist": "Test Artist",
                "duration_seconds": "inf",
            }
        ],
    )

    assert payload["state"] == "unbound"
    assert payload["resolved_track_key"] == ""


def test_resolve_track_identity_ignores_non_mapping_candidates() -> None:
    payload = resolve_track_identity(
        title="Age of Love",
        artist="ARTBAT / Pete Tong",
        duration_seconds=445.4,
        candidates=["bad"],
    )

    assert payload["state"] == "unbound"
    assert payload["resolved_track_key"] == ""


def test_playback_context_apply_live_binding_non_bound_payload_is_no_op() -> None:
    ctx = PlaybackContext(
        file_path="",
        file_name="Live Track",
        duration_seconds=0.0,
        track_title="Live Track",
        track_artist="Original Artist",
        track_key="original-key",
        metadata_source="file_playback",
    )
    before_revision = ctx.transport_revision
    before_metadata_bound_at = ctx.metadata_bound_at
    before = ctx.snapshot()
    snapshot = ctx.apply_live_binding(
        {
            "state": "unbound",
            "resolved_track_key": "ARTBAT / Pete Tong|Age of Love",
            "track_title": "Age of Love",
            "track_artist": "ARTBAT / Pete Tong",
            "duration_seconds": 445.4,
            "playhead_seconds": 183.2,
            "metadata_source": "pro_dj_link",
        }
    )

    assert snapshot == before
    assert ctx.transport_revision == before_revision
    assert ctx.metadata_bound_at == before_metadata_bound_at


def test_playback_context_apply_live_binding_can_explicitly_clear_live_bound_state() -> None:
    ctx = PlaybackContext(
        file_path="",
        file_name="Live Track",
        duration_seconds=445.4,
        track_title="Age of Love",
        track_artist="ARTBAT / Pete Tong",
        track_key="ARTBAT / Pete Tong|Age of Love",
        metadata_source="pro_dj_link",
    )
    ctx.update_transport(
        playhead_seconds=183.2,
        playing=True,
        finished=False,
        realtime=True,
        speed=1.0,
    )

    snapshot = ctx.apply_live_binding(
        {
            "state": "unbound",
            "clear_live_binding": True,
            "track_title": "Another Track",
            "track_artist": "Yotto",
            "duration_seconds": 390.5,
            "metadata_source": "pro_dj_link",
        }
    )

    assert snapshot["track_key"] == ""
    assert snapshot["track_title"] == "Another Track"
    assert snapshot["track_artist"] == "Yotto"
    assert snapshot["playing"] is False
    assert snapshot["realtime"] is False
    assert snapshot["finished"] is False
    assert snapshot["playhead_seconds"] == 0.0


def test_playback_context_apply_live_binding_updates_track_key_and_bumps_transport_revision() -> None:
    ctx = PlaybackContext(file_path="", file_name="Live Track", duration_seconds=0.0, track_title="Live Track")
    before_revision = ctx.transport_revision
    snapshot = ctx.apply_live_binding(
        {
            "state": "bound",
            "resolved_track_key": "ARTBAT / Pete Tong|Age of Love",
            "track_title": "Age of Love",
            "track_artist": "ARTBAT / Pete Tong",
            "duration_seconds": 445.4,
            "playhead_seconds": 183.2,
            "metadata_source": "pro_dj_link",
        }
    )

    assert snapshot["track_key"] == "ARTBAT / Pete Tong|Age of Love"
    assert snapshot["track_title"] == "Age of Love"
    assert snapshot["playhead_seconds"] == 183.2
    assert snapshot["metadata_source"] == "pro_dj_link"
    assert snapshot["transport_revision"] == before_revision + 1
