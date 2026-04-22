from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from threading import Lock

from photonic_synesthesia.platform.live_deck_models import LiveDeckFact, LiveDeckSnapshot


@dataclass(slots=True)
class LiveDeckIngestService:
    _lock: Lock = field(default_factory=Lock, repr=False)
    _live_snapshot: LiveDeckSnapshot = field(default_factory=LiveDeckSnapshot, repr=False)
    _test_snapshot: LiveDeckSnapshot = field(default_factory=LiveDeckSnapshot, repr=False)
    _test_mode_enabled: bool = False

    def publish_live_snapshot(self, decks: list[LiveDeckFact]) -> None:
        snapshot = LiveDeckSnapshot(decks=deepcopy(list(decks)))
        with self._lock:
            self._live_snapshot = snapshot

    def publish_test_snapshot(self, decks: list[LiveDeckFact]) -> None:
        snapshot = LiveDeckSnapshot(decks=deepcopy(list(decks)))
        with self._lock:
            self._test_snapshot = snapshot

    def set_test_mode_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._test_mode_enabled = bool(enabled)

    def current_snapshot(self) -> LiveDeckSnapshot:
        with self._lock:
            source = self._test_snapshot if self._test_mode_enabled else self._live_snapshot
            return LiveDeckSnapshot(decks=deepcopy(source.decks))


@dataclass(slots=True)
class ManualTestIngestAdapter:
    service: LiveDeckIngestService

    def set_enabled(self, enabled: bool) -> None:
        self.service.set_test_mode_enabled(enabled)

    def publish_test_snapshot(self, decks: list[LiveDeckFact]) -> None:
        self.service.publish_test_snapshot(decks)

