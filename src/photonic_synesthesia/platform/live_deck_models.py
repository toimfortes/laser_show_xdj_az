from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class LiveDeckFact:
    player_number: int
    track_title: str = ""
    track_artist: str = ""
    duration_seconds: float = 0.0
    playhead_seconds: float = 0.0
    bpm: float = 0.0
    speed: float = 1.0
    master: bool = False
    on_air: bool = False
    playing: bool = False
    updated_at: float = 0.0
    track_id: str = ""
    source_type: str = ""


@dataclass(slots=True)
class LiveDeckSnapshot:
    decks: list[LiveDeckFact] = field(default_factory=list)


@dataclass(slots=True)
class BindingStatus:
    state: str
    reason: str
    authority_player: int | None = None
    resolved_track_key: str = ""
    match_confidence: float = 0.0
    last_update_at: float = 0.0
