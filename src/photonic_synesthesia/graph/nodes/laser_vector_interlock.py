"""ILDA safety interlock for vector frames."""

from __future__ import annotations

import math
import time
from collections import defaultdict, deque

from photonic_synesthesia.core.config import FixtureConfig, LaserSafetyConfig
from photonic_synesthesia.core.logging import get_logger
from photonic_synesthesia.core.state import ILDAFrame, ILDAPoint, PhotonicState
from photonic_synesthesia.graph.safety import (
    ProtectedHalfPlane,
    is_point_protected,
    protected_half_plane_for_fixture,
)

logger = get_logger(__name__)


def _clamp_int(value: int, min_value: int, max_value: int) -> int:
    return max(min_value, min(max_value, int(value)))


class LaserVectorInterlockNode:
    """
    Enforce safety rules on ILDA vector frames before transport.

    It guarantees the DAC never receives:
    - points outside configured ILDA coordinate bounds
    - excessive point velocity
    - stationary overbright points (minimum movement floor)
    - too many points per frame
    - saturated RGB values
    - excessive transition/blanking frequency
    """

    def __init__(
        self,
        safety: LaserSafetyConfig | None = None,
        *,
        config: LaserSafetyConfig | None = None,
        fixtures: list[FixtureConfig] | None = None,
        min_beat_confidence: float = 0.0,
    ) -> None:
        resolved = safety or config
        if resolved is None:
            raise TypeError("LaserVectorInterlockNode requires safety or config")
        self.config: LaserSafetyConfig = resolved
        self._min_beat_confidence = max(0.0, min(1.0, min_beat_confidence))

        # Cycle-5 panel LS2: vector interlock is the LAST geometric gate
        # before hardware. Re-evaluate the protected half-plane AFTER
        # clamp + velocity scaling + blink limiting, so a mis-calibrated
        # `ilda_y_min` that would clamp a safe point DOWN into the
        # protected zone is caught at the final hop. Uses the SAME
        # shared helper as LaserZoneRuntimeNode so the two nodes can't
        # disagree on the predicate.
        self._protected_half_plane_by_fixture: dict[str, ProtectedHalfPlane] = {
            str(f.id): protected_half_plane_for_fixture(f)
            for f in (fixtures or [])
            if f.type == "laser"
        }

        self._last_point: defaultdict[str, tuple[int, int] | None] = defaultdict(
            lambda: None,
        )
        self._still_streak: defaultdict[str, int] = defaultdict(int)
        self._last_lit_state: defaultdict[str, bool] = defaultdict(lambda: False)
        self._lit_transition_timestamps: defaultdict[str, deque[float]] = defaultdict(deque)

    def __call__(self, state: PhotonicState) -> PhotonicState:
        start_time = time.time()
        beat_confidence = float(state["beat_info"].get("confidence", 1.0))
        timestamp = state["timestamp"]
        state["ilda_frames"] = [
            self._interlock_frame(frame, timestamp, beat_confidence)
            for frame in state["ilda_frames"]
        ]
        state["processing_times"]["laser_vector_interlock"] = time.time() - start_time
        return state

    def _interlock_frame(
        self,
        frame: ILDAFrame,
        now: float,
        beat_confidence: float,
    ) -> ILDAFrame:
        max_points = max(1, self.config.ilda_max_point_count)
        points = frame["points"][:max_points]
        if len(frame["points"]) > max_points:
            logger.debug(
                "ILDA point cap applied",
                fixture=frame["fixture_id"],
                requested=len(frame["points"]),
                allowed=max_points,
            )

        processed: list[ILDAPoint] = []
        last = self._last_point[frame["fixture_id"]]

        for point in points:
            x = _clamp_int(point["x"], self.config.ilda_x_min, self.config.ilda_x_max)
            y = _clamp_int(point["y"], self.config.ilda_y_min, self.config.ilda_y_max)
            r = _clamp_int(point["r"], 0, self.config.ilda_max_color_value)
            g = _clamp_int(point["g"], 0, self.config.ilda_max_color_value)
            b = _clamp_int(point["b"], 0, self.config.ilda_max_color_value)

            is_lit = bool(r or g or b) and not point["blanked"]
            if self._min_beat_confidence and beat_confidence < self._min_beat_confidence:
                scale = max(
                    0.35,
                    beat_confidence / max(1e-6, self._min_beat_confidence),
                )
                r = int(r * scale)
                g = int(g * scale)
                b = int(b * scale)
                is_lit = bool(r or g or b)

            # Motion/scan safety (minimum/maximum point velocity).
            if last is not None:
                dx = x - last[0]
                dy = y - last[1]
                distance = math.hypot(dx, dy)

                if distance <= self.config.ilda_min_point_velocity:
                    self._still_streak[frame["fixture_id"]] += 1
                else:
                    self._still_streak[frame["fixture_id"]] = 0

                if self._still_streak[frame["fixture_id"]] > 0 and is_lit:
                    # Force blanking when movement is below scan-floor.
                    is_lit = False
                elif distance > self.config.ilda_max_point_velocity:
                    scale = self.config.ilda_max_point_velocity / distance
                    x = int(round(last[0] + dx * scale))
                    y = int(round(last[1] + dy * scale))

                if distance <= 0.0 and is_lit:
                    r = g = b = 0
                    is_lit = False

            # Blink-rate/transition limiter.
            if self._needs_blink_limit(frame["fixture_id"], is_lit, now):
                # Suppress this blink transition by blanking the point.
                is_lit = False

            if self._last_lit_state[frame["fixture_id"]] != is_lit:
                self._last_lit_state[frame["fixture_id"]] = is_lit
                if is_lit:
                    self._lit_transition_timestamps[frame["fixture_id"]].append(now)

            if not is_lit:
                r = g = b = 0

            # Cycle-5 panel LS2: final geometric gate. Check the
            # protected half-plane AFTER every coordinate transformation
            # (clamp + velocity scaling + blink limiter) so a
            # mis-calibrated `ilda_{x,y}_{min,max}` that clamped a safe
            # lit point into the protected zone is caught here.
            half_plane = self._protected_half_plane_by_fixture.get(frame["fixture_id"])
            if half_plane is not None:
                value_on_axis = float(y if half_plane.axis == "y" else x)
                if is_point_protected(value_on_axis, half_plane):
                    # Force blank. Do NOT advance `last` with the
                    # contaminated coord — keep the previous safe anchor
                    # so subsequent points' velocity calculations don't
                    # cascade from an in-zone position (Kilo F8).
                    r = g = b = 0
                    is_lit = False
                    processed_point = ILDAPoint(
                        x=x, y=y, r=0, g=0, b=0, blanked=True,
                    )
                    processed.append(processed_point)
                    # `last` stays as the prior safe point; do NOT
                    # update `self._last_point` with (x, y).
                    continue

            processed_point = ILDAPoint(
                x=x,
                y=y,
                r=int(r),
                g=int(g),
                b=int(b),
                blanked=not is_lit,
            )
            processed.append(processed_point)
            last = (x, y)

            # Persist continuity state.
            self._last_point[frame["fixture_id"]] = (x, y)

        if not processed:
            processed.append(ILDAPoint(x=0, y=0, r=0, g=0, b=0, blanked=True))
            self._last_point[frame["fixture_id"]] = (0, 0)
            self._still_streak[frame["fixture_id"]] = 0

        return ILDAFrame(
            fixture_id=frame["fixture_id"],
            profile_name=frame["profile_name"],
            geometry_family=frame["geometry_family"],
            color_mode=frame["color_mode"],
            target_bias=frame["target_bias"],
            point_count=len(processed),
            repeat=frame["repeat"],
            points=processed,
        )

    def _needs_blink_limit(self, fixture_id: str, is_lit: bool, now: float) -> bool:
        """
        Returns True if forcing the point lit would prevent blink-limit violations.
        """
        if self.config.ilda_max_blink_hz <= 0:
            return False
        if not is_lit:
            return False

        history = self._lit_transition_timestamps[fixture_id]
        window_start = now - 1.0
        while history and history[0] < window_start:
            history.popleft()

        if len(history) < int(math.floor(self.config.ilda_max_blink_hz)):
            return False
        logger.debug(
            "ILDA blink limit exceeded",
            fixture=fixture_id,
            recent_transitions=len(history),
            max_blink_hz=self.config.ilda_max_blink_hz,
        )
        return True
