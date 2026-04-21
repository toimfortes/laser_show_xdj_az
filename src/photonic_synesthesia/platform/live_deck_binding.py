from __future__ import annotations

from dataclasses import dataclass

from photonic_synesthesia.platform.live_deck_models import BindingStatus, LiveDeckFact


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
