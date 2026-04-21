"""In-memory command bus scaffolding for the control plane."""

from __future__ import annotations

import threading
from collections import deque

from pydantic import BaseModel, Field

from photonic_synesthesia.platform.contracts import OperatorCommand


class CommandReceipt(BaseModel):
    """Result of publishing a command to the bus."""

    accepted: bool
    command_id: str
    queue_depth: int = Field(ge=0)
    message: str


class InMemoryCommandBus:
    """Simple in-memory command queue with recent history."""

    def __init__(self, max_recent: int = 256, max_queue: int = 1024):
        self._lock = threading.Lock()
        self._max_queue = max(1, int(max_queue))
        self._queue: deque[OperatorCommand] = deque()
        self._recent: deque[OperatorCommand] = deque(maxlen=max_recent)

    def publish(self, command: OperatorCommand) -> CommandReceipt:
        with self._lock:
            if len(self._queue) >= self._max_queue:
                depth = len(self._queue)
                return CommandReceipt(
                    accepted=False,
                    command_id=command.command_id,
                    queue_depth=depth,
                    message=(
                        "Command rejected: in-memory bus backlog is full; "
                        "wait for graph consumption before retrying"
                    ),
                )
            self._queue.append(command)
            self._recent.append(command)
            depth = len(self._queue)
        return CommandReceipt(
            accepted=True,
            command_id=command.command_id,
            queue_depth=depth,
            message="Command accepted into in-memory bus",
        )

    def drain(self) -> list[OperatorCommand]:
        with self._lock:
            items = list(self._queue)
            self._queue.clear()
            return items

    def backlog(self) -> int:
        with self._lock:
            return len(self._queue)

    def recent(self) -> list[OperatorCommand]:
        with self._lock:
            return list(self._recent)
