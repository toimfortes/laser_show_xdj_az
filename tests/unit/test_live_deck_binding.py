from photonic_synesthesia.platform import (
    BindingStatus as PlatformBindingStatus,
    LiveDeckFact as PlatformLiveDeckFact,
    LiveDeckSnapshot as PlatformLiveDeckSnapshot,
)
from photonic_synesthesia.platform.live_deck_models import (
    BindingStatus,
    LiveDeckFact,
    LiveDeckSnapshot,
)


def test_live_deck_fact_allows_missing_nonessential_metadata() -> None:
    fact = LiveDeckFact(
        player_number=3,
        playhead_seconds=183.2,
        speed=1.0,
        master=True,
        on_air=True,
        playing=True,
        updated_at=1713660000.0,
    )

    assert fact.player_number == 3
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
        playhead_seconds=183.2,
        speed=1.0,
        master=True,
        on_air=True,
        playing=True,
        updated_at=1713660000.0,
    )
    snapshot = LiveDeckSnapshot(decks=[fact])

    assert snapshot.decks[0].player_number == 3
    assert snapshot.decks[0].track_id is None


def test_live_deck_snapshot_can_be_empty() -> None:
    snapshot = LiveDeckSnapshot(decks=[])

    assert snapshot.decks == []
