from photonic_synesthesia.platform import (
    BindingStatus as PlatformBindingStatus,
    LiveDeckFact as PlatformLiveDeckFact,
    LiveDeckSnapshot as PlatformLiveDeckSnapshot,
)
from photonic_synesthesia.platform.live_deck_binding import LiveDeckAutoBindEngine
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
