from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class LiveDeckFact:
    player_number: int
    playhead_seconds: float
    speed: float
    master: bool
    on_air: bool
    playing: bool
    updated_at: float
    track_id: str
    source_type: str
    track_title: str | None = None
    track_artist: str | None = None
    duration_seconds: float | None = None
    bpm: float | None = None


@dataclass(slots=True)
class LiveDeckSnapshot:
    decks: list[LiveDeckFact]


@dataclass(slots=True)
class BindingStatus:
    state: str
    reason: str
    authority_player: int | None
    resolved_track_key: str
    match_confidence: float
    last_update_at: float
