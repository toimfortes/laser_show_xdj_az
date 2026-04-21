from photonic_synesthesia.platform.live_deck_models import (
    BindingStatus,
    LiveDeckFact,
    LiveDeckSnapshot,
)


def test_live_deck_fact_normalizes_core_fields() -> None:
    fact = LiveDeckFact(
        player_number=3,
        track_title="Age of Love",
        track_artist="ARTBAT / Pete Tong",
        duration_seconds=445.4,
        playhead_seconds=183.2,
        bpm=128.0,
        speed=1.0,
        master=True,
        on_air=True,
        playing=True,
        updated_at=1713660000.0,
        track_id="track-1",
        source_type="xdj",
    )

    assert fact.player_number == 3
    assert fact.track_title == "Age of Love"
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


def test_live_deck_snapshot_wraps_decks() -> None:
    fact = LiveDeckFact(
        player_number=3,
        track_title="Age of Love",
        track_artist="ARTBAT / Pete Tong",
        duration_seconds=445.4,
        playhead_seconds=183.2,
        bpm=128.0,
        speed=1.0,
        master=True,
        on_air=True,
        playing=True,
        updated_at=1713660000.0,
        track_id="track-1",
        source_type="xdj",
    )
    snapshot = LiveDeckSnapshot(decks=[fact])

    assert snapshot.decks[0].player_number == 3
    assert snapshot.decks[0].track_id == "track-1"
