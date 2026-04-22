from __future__ import annotations

from photonic_synesthesia.core.config import ProDJLinkConfig
from photonic_synesthesia.platform import (
    LiveDeckFact as PlatformLiveDeckFact,
    LiveDeckIngestService as PlatformLiveDeckIngestService,
    LiveDeckSnapshot as PlatformLiveDeckSnapshot,
    ManualTestIngestAdapter as PlatformManualTestIngestAdapter,
)
from photonic_synesthesia.platform.live_deck_ingest import (
    LiveDeckFact,
    LiveDeckIngestService,
    LiveDeckSnapshot,
    ManualTestIngestAdapter,
)


def _deck(player_number: int, updated_at: float, *, master: bool = True, on_air: bool = True) -> LiveDeckFact:
    return LiveDeckFact(
        player_number=player_number,
        master=master,
        on_air=on_air,
        updated_at=updated_at,
    )


def test_live_deck_ingest_service_defaults_to_live_snapshot() -> None:
    service = LiveDeckIngestService()
    live_decks = [_deck(3, 100.0)]

    service.publish_live_snapshot(live_decks)

    snapshot = service.current_snapshot()
    assert snapshot.decks == live_decks
    assert snapshot.decks is not live_decks


def test_live_deck_ingest_service_keeps_manual_snapshot_hidden_until_test_mode_enabled() -> None:
    service = LiveDeckIngestService()
    service.publish_live_snapshot([_deck(3, 100.0)])
    service.publish_test_snapshot([_deck(4, 101.0)])

    assert [deck.player_number for deck in service.current_snapshot().decks] == [3]

    service.set_test_mode_enabled(True)

    assert [deck.player_number for deck in service.current_snapshot().decks] == [4]


def test_live_deck_ingest_service_replaces_live_snapshot_without_aliasing_input_list() -> None:
    service = LiveDeckIngestService()
    live_decks = [_deck(3, 100.0)]

    service.publish_live_snapshot(live_decks)
    live_decks.append(_deck(4, 101.0))

    snapshot = service.current_snapshot()

    assert [deck.player_number for deck in snapshot.decks] == [3]
    assert snapshot.decks is not live_decks


def test_live_deck_ingest_service_replaces_test_snapshot_without_aliasing_input_list() -> None:
    service = LiveDeckIngestService()
    test_decks = [_deck(4, 101.0)]

    service.publish_test_snapshot(test_decks)
    service.set_test_mode_enabled(True)
    test_decks.append(_deck(5, 102.0))

    snapshot = service.current_snapshot()

    assert [deck.player_number for deck in snapshot.decks] == [4]
    assert snapshot.decks is not test_decks


def test_manual_test_ingest_adapter_forwards_enable_and_test_snapshot() -> None:
    service = LiveDeckIngestService()
    adapter = ManualTestIngestAdapter(service)

    adapter.publish_test_snapshot([_deck(5, 102.0)])
    assert [deck.player_number for deck in service.current_snapshot().decks] == []

    adapter.set_enabled(True)
    assert [deck.player_number for deck in service.current_snapshot().decks] == [5]


def test_platform_reexports_live_deck_ingest_types() -> None:
    assert PlatformLiveDeckFact is LiveDeckFact
    assert PlatformLiveDeckSnapshot is LiveDeckSnapshot
    assert PlatformLiveDeckIngestService is LiveDeckIngestService
    assert PlatformManualTestIngestAdapter is ManualTestIngestAdapter


def test_pro_dj_link_config_includes_ingest_runtime_fields() -> None:
    config = ProDJLinkConfig()

    assert config.enabled is False
    assert config.ingest_mode == "tcnet"
    assert config.freshness_threshold_seconds == 0.5
    assert config.listen_host == "127.0.0.1"
    assert config.keepalive_port == 50000
    assert config.status_port == 50001
    assert config.beat_port == 50002
