from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class LiveDeckFact:
    player_number: int
    track_title: str
    track_artist: str
    duration_seconds: float
    playhead_seconds: float
    bpm: float
    speed: float
    master: bool
    on_air: bool
    playing: bool
    updated_at: float
    track_id: str
    source_type: str


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
