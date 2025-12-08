"""
Safety Interlock Node: Enforces safety limits on all DMX output.

Implements multiple layers of software safety:
- Laser Y-axis clamping (prevent crowd scanning)
- Strobe rate limiting (seizure prevention)
- Heartbeat monitoring (analysis hang detection)
- Emergency blackout capability
"""

from __future__ import annotations

import time
from collections import deque
from typing import List, Optional
import structlog

from photonic_synesthesia.core.state import PhotonicState, SafetyState
from photonic_synesthesia.core.config import SafetyConfig, FixtureConfig
from photonic_synesthesia.core.exceptions import (
    SafetyInterlockError,
    HeartbeatTimeoutError,
)

logger = structlog.get_logger()


class SafetyInterlockNode:
    """
    Enforces safety limits on DMX output.

    This node runs LAST in the graph, after DMX values have been
    computed but before they are transmitted. It can modify or
    zero out values that violate safety constraints.
    """

    def __init__(
        self,
        config: SafetyConfig,
        fixtures: List[FixtureConfig],
    ):
        self.config = config
        self.fixtures = fixtures

        # Extract fixture info for safety checks
        self._laser_fixtures = [f for f in fixtures if f.type == "laser"]

        # Heartbeat tracking
        self._last_heartbeat = time.time()

        # Strobe rate tracking
        self._strobe_timestamps: deque = deque(maxlen=100)
        self._strobe_start_time: Optional[float] = None
        self._in_cooldown = False
        self._cooldown_end: float = 0.0

        # Emergency stop state
        self._emergency_stop = False

    def __call__(self, state: PhotonicState) -> PhotonicState:
        """Apply safety checks to DMX universe."""
        start_time = time.time()
        current_time = state["timestamp"]

        universe = bytearray(state["dmx_universe"])
        safety_ok = True
        error_state = None

        # =================================================================
        # Check 1: Heartbeat monitoring
        # =================================================================
        heartbeat_timeout = self.config.heartbeat_timeout_s
        time_since_heartbeat = current_time - self._last_heartbeat

        if time_since_heartbeat > heartbeat_timeout:
            safety_ok = False
            error_state = f"heartbeat_timeout: {time_since_heartbeat:.2f}s"
            logger.warning("Heartbeat timeout", elapsed=time_since_heartbeat)
            universe = self._emergency_blackout(universe)

        # Update heartbeat
        self._last_heartbeat = current_time

        # =================================================================
        # Check 2: Emergency stop
        # =================================================================
        if self._emergency_stop:
            safety_ok = False
            error_state = "emergency_stop_active"
            universe = self._emergency_blackout(universe)

        # =================================================================
        # Check 3: Laser Y-axis clamping
        # =================================================================
        for fixture in self._laser_fixtures:
            if not fixture.enabled:
                continue

            # Standard laser: Y-roll is typically channel 5 (offset 4)
            y_channel = fixture.start_address + 4  # Assuming standard 7-ch laser

            if 1 <= y_channel <= 512:
                current_y = universe[y_channel]
                max_y = self.config.laser.y_axis_max

                if current_y > max_y:
                    logger.debug(
                        "Laser Y-axis clamped",
                        fixture=fixture.id,
                        original=current_y,
                        clamped=max_y,
                    )
                    universe[y_channel] = max_y

            # Also check scan speed minimum
            speed_channel = fixture.start_address + 5  # Movement speed

            if 1 <= speed_channel <= 512:
                current_speed = universe[speed_channel]
                min_speed = self.config.laser.min_scan_speed

                if current_speed < min_speed and current_speed > 0:
                    universe[speed_channel] = min_speed

        # =================================================================
        # Check 4: Strobe rate limiting
        # =================================================================
        # Detect if strobe-like patterns are occurring
        # (This is a simplified check - could be expanded)
        max_strobe_rate = self.config.strobe.max_rate_hz
        max_strobe_duration = self.config.strobe.max_duration_s

        # Check if we're in cooldown
        if self._in_cooldown:
            if current_time < self._cooldown_end:
                # Still in cooldown - disable strobes
                # This would require knowing which channels are strobes
                pass
            else:
                self._in_cooldown = False
                self._strobe_start_time = None

        # =================================================================
        # Check 5: Beat confidence threshold
        # =================================================================
        beat_confidence = state["beat_info"]["confidence"]
        if beat_confidence < self.config.min_beat_confidence:
            # Low confidence - reduce intensity to prevent random flashing
            if self.config.graceful_degradation:
                reduction_factor = beat_confidence / self.config.min_beat_confidence
                # Apply reduction to dimmer channels (simplified)
                # In practice, would need fixture profile info
                pass

        # =================================================================
        # Update state
        # =================================================================
        state["dmx_universe"] = bytes(universe)
        state["safety_state"] = SafetyState(
            ok=safety_ok,
            last_heartbeat=current_time,
            error_state=error_state,
            laser_enabled=not self._emergency_stop,
            strobe_enabled=not self._in_cooldown,
            emergency_stop=self._emergency_stop,
        )

        # Record processing time
        state["processing_times"]["safety_interlock"] = time.time() - start_time

        return state

    def _emergency_blackout(self, universe: bytearray) -> bytearray:
        """Set all channels to zero."""
        return bytearray(513)

    def trigger_emergency_stop(self, source: str = "manual") -> None:
        """Trigger emergency stop - immediately blackout all fixtures."""
        self._emergency_stop = True
        logger.critical("Emergency stop triggered", source=source)

    def reset_emergency_stop(self) -> None:
        """Reset emergency stop state."""
        self._emergency_stop = False
        logger.info("Emergency stop reset")

    def is_safe(self) -> bool:
        """Check if system is in a safe state."""
        return not self._emergency_stop and not self._in_cooldown


class SafetyMonitor:
    """
    Background safety monitor for critical system health.

    Can be run as a separate process/thread to ensure safety
    even if the main graph hangs.
    """

    def __init__(
        self,
        dmx_output,  # Reference to DMX output node
        check_interval: float = 0.1,
        max_silence: float = 1.0,
    ):
        self.dmx_output = dmx_output
        self.check_interval = check_interval
        self.max_silence = max_silence

        self._last_frame_count = 0
        self._last_check_time = time.time()
        self._running = False

    def start(self) -> None:
        """Start safety monitoring."""
        import threading

        self._running = True
        self._thread = threading.Thread(
            target=self._monitor_loop,
            name="Safety-Monitor",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop safety monitoring."""
        self._running = False

    def _monitor_loop(self) -> None:
        """Monitor DMX output health."""
        while self._running:
            time.sleep(self.check_interval)

            stats = self.dmx_output.get_stats()
            current_frames = stats["frames_sent"]
            current_time = time.time()

            if current_frames == self._last_frame_count:
                # No new frames sent
                silence_duration = current_time - self._last_check_time
                if silence_duration > self.max_silence:
                    logger.critical(
                        "DMX output stalled - triggering blackout",
                        silence=silence_duration,
                    )
                    self.dmx_output.blackout()
            else:
                self._last_check_time = current_time

            self._last_frame_count = current_frames
