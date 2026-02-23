"""Safety-focused command interpreter."""

from __future__ import annotations

from photonic_synesthesia.core.config import SafetyConfig
from photonic_synesthesia.core.state import FixtureCommand


class SafetyConstraintInterpreter:
    """
    Shapes raw fixture commands into hardware-safe transitions.

    The interpreter applies:
    - per-frame channel delta limiting
    - laser Y-axis and scan-speed safety constraints
    - strobe budget clamping from director state
    """

    def __init__(self, safety: SafetyConfig, max_delta_per_frame: int = 36):
        self.safety = safety
        self.max_delta_per_frame = max(1, max_delta_per_frame)
        self._last_channel_values: dict[int, int] = {}

    def interpret(
        self,
        commands: list[FixtureCommand],
        strobe_budget_hz: float,
    ) -> list[FixtureCommand]:
        interpreted: list[FixtureCommand] = []
        for command in commands:
            interpreted.append(self._interpret_single(command, strobe_budget_hz=strobe_budget_hz))
        return interpreted

    def _interpret_single(
        self,
        command: FixtureCommand,
        strobe_budget_hz: float,
    ) -> FixtureCommand:
        fixture_type = command["fixture_type"]
        values = dict(command["channel_values"])
        base = min(values.keys()) if values else 1

        if fixture_type == "laser":
            y_channel = base + self.safety.laser.y_channel_offset
            movement_channel = base + self.safety.laser.speed_channel_offset
            if y_channel in values:
                values[y_channel] = min(values[y_channel], self.safety.laser.y_axis_max)
            if movement_channel in values:
                values[movement_channel] = max(
                    values[movement_channel], self.safety.laser.min_scan_speed
                )

        strobe_limit = self._strobe_budget_to_dmx(strobe_budget_hz)
        if fixture_type == "moving_head":
            strobe_channel = base + 6
            if strobe_channel in values:
                values[strobe_channel] = min(values[strobe_channel], strobe_limit)
        elif fixture_type == "panel":
            strobe_channel = base + 4
            if strobe_channel in values:
                values[strobe_channel] = min(values[strobe_channel], strobe_limit)

        smoothed: dict[int, int] = {}
        for channel, target in values.items():
            prev = self._last_channel_values.get(channel, 0)
            delta = target - prev
            if delta > self.max_delta_per_frame:
                target = prev + self.max_delta_per_frame
            elif delta < -self.max_delta_per_frame:
                target = prev - self.max_delta_per_frame

            clamped = int(min(255, max(0, target)))
            smoothed[channel] = clamped
            self._last_channel_values[channel] = clamped

        return FixtureCommand(
            fixture_id=command["fixture_id"],
            fixture_type=fixture_type,
            channel_values=smoothed,
        )

    def _strobe_budget_to_dmx(self, strobe_budget_hz: float) -> int:
        max_safe_hz = max(0.1, self.safety.strobe.max_rate_hz)
        ratio = min(1.0, max(0.0, strobe_budget_hz / max_safe_hz))
        return int(ratio * 255)
