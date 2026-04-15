"""Clock abstractions for runtime and replay work."""

from __future__ import annotations

import time
from datetime import UTC, datetime


class PlatformClock:
    """Abstract clock surface for live and replay contexts."""

    def now(self) -> datetime:
        raise NotImplementedError

    def now_ms(self) -> int:
        return int(self.now().timestamp() * 1000)

    def monotonic_ms(self) -> int:
        raise NotImplementedError


class SystemClock(PlatformClock):
    """System-backed wall and monotonic clock."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic_ms(self) -> int:
        return int(time.monotonic() * 1000)
