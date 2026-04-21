from __future__ import annotations

from dataclasses import dataclass

from photonic_synesthesia.platform.live_deck_models import BindingStatus, LiveDeckFact


def resolve_track_identity(
    *,
    title: str,
    artist: str,
    duration_seconds: float,
    candidates: list[dict[str, object]],
) -> dict[str, object]:
    exact = [
        candidate
        for candidate in candidates
        if str(candidate.get("track_title") or "") == title
        and str(candidate.get("track_artist") or "") == artist
        and float(candidate.get("duration_seconds") or 0.0) == duration_seconds
    ]
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
        authoritative = [deck for deck in decks if deck.on_air and deck.master]

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
            deck = authoritative[0]
            deck_updated_at = float(deck.updated_at)
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
                last_update_at=float(deck.updated_at),
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
