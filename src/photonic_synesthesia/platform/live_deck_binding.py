from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from photonic_synesthesia.platform.live_deck_models import BindingStatus, LiveDeckFact

if TYPE_CHECKING:
    from photonic_synesthesia.platform.runtime_context import PlaybackContext

_TRACK_DURATION_TOLERANCE_SECONDS = 1.0


def _coerce_finite_timestamp(value: object) -> float | None:
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(timestamp):
        return None
    return timestamp


def resolve_track_identity(
    *,
    title: str,
    artist: str,
    duration_seconds: float,
    candidates: list[dict[str, object]],
) -> dict[str, object]:
    try:
        target_duration = float(duration_seconds)
    except (TypeError, ValueError):
        return {"state": "unbound", "resolved_track_key": "", "match_confidence": 0.0}
    if not math.isfinite(target_duration):
        return {"state": "unbound", "resolved_track_key": "", "match_confidence": 0.0}

    exact: list[dict[str, object]] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        if str(candidate.get("track_title") or "") != title:
            continue
        if str(candidate.get("track_artist") or "") != artist:
            continue
        raw_duration = candidate.get("duration_seconds")
        if raw_duration is None:
            continue
        try:
            candidate_duration = float(raw_duration)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(candidate_duration):
            continue
        if abs(candidate_duration - target_duration) > _TRACK_DURATION_TOLERANCE_SECONDS:
            continue
        if not str(candidate.get("track_key") or "").strip():
            continue
        exact.append(candidate)
    if len(exact) == 1:
        winner = exact[0]
        return {
            "state": "bound",
            "resolved_track_key": str(winner.get("track_key") or ""),
            "match_confidence": 1.0,
        }
    if len(exact) > 1:
        return {"state": "ambiguous", "resolved_track_key": "", "match_confidence": 0.0}
    return {"state": "unbound", "resolved_track_key": "", "match_confidence": 0.0}


@dataclass(slots=True)
class LiveDeckAutoBindEngine:
    stale_after_seconds: float = 0.5
    _last_authority_player: int | None = None
    _last_authority_at: float = 0.0

    def evaluate(self, decks: list[LiveDeckFact], *, now: float) -> BindingStatus:
        authoritative: list[tuple[LiveDeckFact, float]] = []
        invalid_authority_present = False
        for deck in decks:
            if not (deck.on_air and deck.master):
                continue
            deck_updated_at = _coerce_finite_timestamp(deck.updated_at)
            if deck_updated_at is None:
                invalid_authority_present = True
                continue
            authoritative.append((deck, deck_updated_at))

        if len(authoritative) > 1:
            self._last_authority_player = None
            self._last_authority_at = 0.0
            return BindingStatus(
                state="conflict",
                reason="multiple on-air master decks",
                authority_player=None,
                last_update_at=now,
            )

        if len(authoritative) == 1:
            deck, deck_updated_at = authoritative[0]
            if (
                self._last_authority_player is not None
                and deck.player_number == self._last_authority_player
                and deck_updated_at < self._last_authority_at
            ):
                if now - self._last_authority_at >= self.stale_after_seconds:
                    return BindingStatus(
                        state="stale",
                        reason="authoritative deck timed out",
                        authority_player=self._last_authority_player,
                        last_update_at=self._last_authority_at,
                    )
                return BindingStatus(
                    state="bound",
                    reason="authoritative deck resolved",
                    authority_player=self._last_authority_player,
                    last_update_at=self._last_authority_at,
                )

            self._last_authority_player = deck.player_number
            self._last_authority_at = deck_updated_at
            if now - self._last_authority_at >= self.stale_after_seconds:
                return BindingStatus(
                    state="stale",
                    reason="authoritative deck timed out",
                    authority_player=deck.player_number,
                    last_update_at=self._last_authority_at,
                )
            return BindingStatus(
                state="bound",
                reason="authoritative deck resolved",
                authority_player=deck.player_number,
                last_update_at=deck_updated_at,
            )

        if invalid_authority_present:
            self._last_authority_player = None
            self._last_authority_at = 0.0
            return BindingStatus(
                state="unbound",
                reason="authoritative deck timestamp is invalid",
                authority_player=None,
                last_update_at=now,
            )

        if (
            self._last_authority_player is not None
            and now - self._last_authority_at >= self.stale_after_seconds
        ):
            return BindingStatus(
                state="stale",
                reason="authoritative deck timed out",
                authority_player=self._last_authority_player,
                last_update_at=self._last_authority_at,
            )

        return BindingStatus(
            state="unbound",
            reason="no on-air master deck",
            authority_player=None,
            last_update_at=now,
        )


def _authoritative_deck_for_player(
    decks: list[LiveDeckFact], authority_player: int | None
) -> LiveDeckFact | None:
    if authority_player is None:
        return None
    for deck in decks:
        if deck.player_number == authority_player and deck.on_air and deck.master:
            return deck
    return None


def _coerce_authority_track_metadata(deck: LiveDeckFact) -> tuple[str, str, float] | None:
    if not isinstance(deck.track_title, str) or not deck.track_title.strip():
        return None
    if not isinstance(deck.track_artist, str) or not deck.track_artist.strip():
        return None
    raw_duration = deck.duration_seconds
    if isinstance(raw_duration, bool) or raw_duration is None:
        return None
    try:
        duration_seconds = float(raw_duration)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(duration_seconds):
        return None
    return deck.track_title.strip(), deck.track_artist.strip(), duration_seconds


def _clear_payload_from_deck(deck: LiveDeckFact | None) -> dict[str, object]:
    payload: dict[str, object] = {
        "state": "unbound",
        "clear_live_binding": True,
    }
    if deck is None:
        return payload
    if isinstance(deck.track_title, str) and deck.track_title.strip():
        payload["track_title"] = deck.track_title.strip()
    if isinstance(deck.track_artist, str) and deck.track_artist.strip():
        payload["track_artist"] = deck.track_artist.strip()
    raw_duration = deck.duration_seconds
    if not isinstance(raw_duration, bool) and raw_duration is not None:
        try:
            duration_seconds = float(raw_duration)
        except (TypeError, ValueError):
            duration_seconds = None
        if duration_seconds is not None and math.isfinite(duration_seconds):
            payload["duration_seconds"] = duration_seconds
    if deck.source_type:
        payload["metadata_source"] = deck.source_type
    return payload


def _should_clear_previous_binding(previous_status: BindingStatus | None) -> bool:
    if previous_status is None:
        return False
    if previous_status.state != "unbound":
        return True
    return bool(previous_status.resolved_track_key)


def apply_live_deck_binding_snapshot(
    *,
    decks: list[LiveDeckFact],
    playback_context: "PlaybackContext",
    track_candidates: list[dict[str, object]],
    now: float,
    engine: LiveDeckAutoBindEngine,
    previous_status: BindingStatus | None = None,
) -> BindingStatus:
    authority_status = engine.evaluate(decks, now=now)
    if authority_status.state != "bound":
        if _should_clear_previous_binding(previous_status):
            playback_context.apply_live_binding(_clear_payload_from_deck(None))
        return authority_status

    authority_deck = _authoritative_deck_for_player(decks, authority_status.authority_player)
    if authority_deck is None:
        if _should_clear_previous_binding(previous_status):
            playback_context.apply_live_binding(_clear_payload_from_deck(None))
        return BindingStatus(
            state="unbound",
            reason="authoritative deck missing from ingest snapshot",
            authority_player=authority_status.authority_player,
            last_update_at=authority_status.last_update_at,
        )
    authority_deck_updated_at = _coerce_finite_timestamp(authority_deck.updated_at)
    if authority_deck_updated_at is None:
        if _should_clear_previous_binding(previous_status):
            playback_context.apply_live_binding(_clear_payload_from_deck(authority_deck))
        return BindingStatus(
            state="unbound",
            reason="authoritative deck timestamp is invalid",
            authority_player=authority_status.authority_player,
            last_update_at=authority_status.last_update_at,
        )
    if (
        authority_status.last_update_at is not None
        and authority_deck_updated_at < authority_status.last_update_at
    ):
        if (
            previous_status is not None
            and previous_status.authority_player == authority_status.authority_player
            and previous_status.last_update_at == authority_status.last_update_at
        ):
            return BindingStatus(
                state=previous_status.state,
                reason=previous_status.reason,
                authority_player=previous_status.authority_player,
                resolved_track_key=previous_status.resolved_track_key,
                match_confidence=previous_status.match_confidence,
                last_update_at=previous_status.last_update_at,
            )
        return BindingStatus(
            state="unbound",
            reason="authoritative deck snapshot older than cached authority",
            authority_player=authority_status.authority_player,
            last_update_at=authority_status.last_update_at,
        )

    track_metadata = _coerce_authority_track_metadata(authority_deck)
    if track_metadata is None:
        if _should_clear_previous_binding(previous_status):
            playback_context.apply_live_binding(_clear_payload_from_deck(authority_deck))
        return BindingStatus(
            state="unbound",
            reason="authority deck metadata incomplete for track resolution",
            authority_player=authority_status.authority_player,
            last_update_at=authority_status.last_update_at,
        )
    track_title, track_artist, duration_seconds = track_metadata

    resolution = resolve_track_identity(
        title=track_title,
        artist=track_artist,
        duration_seconds=duration_seconds,
        candidates=track_candidates,
    )
    resolution_state = str(resolution.get("state") or "unbound")
    if resolution_state != "bound":
        reason = "authority deck track could not be resolved"
        if resolution_state == "ambiguous":
            reason = "authority deck track matched multiple candidates"
        if _should_clear_previous_binding(previous_status):
            playback_context.apply_live_binding(_clear_payload_from_deck(authority_deck))
        return BindingStatus(
            state=resolution_state if resolution_state in {"ambiguous", "unbound"} else "unbound",
            reason=reason,
            authority_player=authority_status.authority_player,
            last_update_at=authority_status.last_update_at,
        )

    payload: dict[str, object] = {
        "state": "bound",
        "resolved_track_key": str(resolution.get("resolved_track_key") or ""),
        "track_title": track_title,
        "track_artist": track_artist,
        "duration_seconds": duration_seconds,
        "metadata_source": authority_deck.source_type or "pro_dj_link",
    }
    if authority_deck.playhead_seconds is not None:
        payload["playhead_seconds"] = authority_deck.playhead_seconds
    if authority_deck.speed is not None:
        payload["speed"] = authority_deck.speed
    if authority_deck.playing is not None:
        payload["playing"] = authority_deck.playing
    playback_context.apply_live_binding(payload)

    match_confidence = resolution.get("match_confidence")
    return BindingStatus(
        state="bound",
        reason="authoritative deck resolved",
        authority_player=authority_status.authority_player,
        resolved_track_key=str(resolution.get("resolved_track_key") or ""),
        match_confidence=float(match_confidence) if match_confidence is not None else None,
        last_update_at=authority_status.last_update_at,
    )


def evaluate_and_apply_live_binding(
    *,
    playback_context: "PlaybackContext",
    ingest_service: object,
    now: float,
    candidates: list[dict[str, object]],
    engine: LiveDeckAutoBindEngine,
    previous_status: BindingStatus | None = None,
) -> BindingStatus:
    snapshot_source = getattr(ingest_service, "service", ingest_service)
    current_snapshot = getattr(snapshot_source, "current_snapshot", None)
    if not callable(current_snapshot):
        return BindingStatus(
            state="unbound",
            reason="live deck ingest source unavailable",
            authority_player=None,
            last_update_at=now,
        )
    snapshot = current_snapshot()
    decks = list(getattr(snapshot, "decks", []))
    return apply_live_deck_binding_snapshot(
        decks=decks,
        playback_context=playback_context,
        track_candidates=candidates,
        now=now,
        engine=engine,
        previous_status=previous_status,
    )
