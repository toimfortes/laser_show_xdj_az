"""In-memory event bus scaffolding for telemetry fan-out."""

from __future__ import annotations

import threading
from collections import deque

from photonic_synesthesia.platform.contracts import PlatformEvent


class InMemoryEventBus:
    """Simple recent-event store for web telemetry and future fan-out."""

    def __init__(self, max_recent: int = 512):
        self._lock = threading.Lock()
        self._recent: deque[PlatformEvent] = deque(maxlen=max_recent)

    def publish(self, event: PlatformEvent) -> None:
        with self._lock:
            self._recent.append(event)

    def recent(self) -> list[PlatformEvent]:
        with self._lock:
            return list(self._recent)

    def count(self) -> int:
        with self._lock:
            return len(self._recent)
