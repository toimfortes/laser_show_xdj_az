"""
Safety Interlock Node: Enforces safety limits on all DMX output.

Implements multiple layers of software safety:
- Laser Y-axis clamping (prevent crowd scanning)
- Strobe rate limiting (seizure prevention)
- Heartbeat monitoring (analysis hang detection)
- Emergency blackout capability
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Protocol

from photonic_synesthesia.core.config import FixtureConfig, SafetyConfig
from photonic_synesthesia.core.logging import get_logger
from photonic_synesthesia.core.state import PhotonicState, SafetyState
from photonic_synesthesia.core.threadhygiene import StopSignal, join_or_raise
from photonic_synesthesia.dmx.universe import create_universe_buffer, is_valid_dmx_channel

logger = get_logger(__name__)


class SupportsBlackout(Protocol):
    """Minimal DMX output protocol needed by watchdogs."""

    def blackout(self) -> None:
        """Immediately zero output."""


class SupportsEmergencyBlackout(Protocol):
    """Optional immediate emergency shutdown API."""

    def emergency_blackout(self) -> None:
        """Immediately force zero output."""


class SupportsBlackoutRequest(SupportsBlackout, Protocol):
    """Optional non-blocking blackout latch API for watchdog callbacks."""

    def request_blackout(self) -> None:
        """Request blackout asynchronously."""


class SupportsBlackoutAndStats(SupportsBlackout, Protocol):
    """DMX protocol needed for frame-stall monitoring."""

    def get_stats(self) -> dict[str, int | float | bool]:
        """Return DMX output stats."""


class HeartbeatWatchdog:
    """Independent watchdog that blackouts output if heartbeat stops.

    Cycle-6 B1: uses `StopSignal` + `join_or_raise` so a wedged
    watchdog surfaces loudly instead of silently leaking. A leaked
    watchdog was the exact pattern that hammered closed shmem in
    yesterday's crash — the class is small but safety-critical.
    """

    def __init__(
        self,
        on_timeout: Callable[[], None],
        timeout_s: float,
        check_interval_s: float = 0.1,
    ) -> None:
        self._on_timeout = on_timeout
        self._timeout_s = max(timeout_s, 0.05)
        self._check_interval_s = max(check_interval_s, 0.01)
        self._last_heartbeat = time.monotonic()
        self._timeout_triggered = False
        self._stop_signal = StopSignal()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start watchdog loop."""
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError(
                "Heartbeat-Watchdog already running; refusing to double-start. "
                "A previous stop() likely left a zombie — see threadhygiene."
            )
        self._stop_signal.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="Heartbeat-Watchdog",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop watchdog loop. Raises if the worker fails to exit."""
        self._stop_signal.stop()
        try:
            join_or_raise(self._thread, timeout=1.0, name="Heartbeat-Watchdog")
        finally:
            self._thread = None

    def beat(self) -> None:
        """Update heartbeat timestamp and clear prior timeout latch."""
        self._last_heartbeat = time.monotonic()
        self._timeout_triggered = False

    def _run_loop(self) -> None:
        while not self._stop_signal.stopped():
            # Wake immediately on stop, not on the next sleep boundary.
            self._stop_signal.wait(self._check_interval_s)
            if self._stop_signal.stopped():
                break
            elapsed = time.monotonic() - self._last_heartbeat
            if elapsed > self._timeout_s and not self._timeout_triggered:
                self._timeout_triggered = True
                logger.critical(
                    "Heartbeat watchdog timeout - triggering blackout",
                    elapsed=round(elapsed, 3),
                )
                self._on_timeout()


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
        fixtures: list[FixtureConfig],
        dmx_output: SupportsBlackout | None = None,
        ilda_output: SupportsBlackout | SupportsEmergencyBlackout | None = None,
        *,
        require_watchdog: bool = False,
    ) -> None:
        """Build a safety interlock node.

        Args:
            config: safety limits and heartbeat timeout.
            fixtures: fixtures whose channels need clamping.
            dmx_output: DMX transmitter exposing ``blackout()`` (or
                ``request_blackout()``). Needed for the watchdog.
            ilda_output: ILDA transmitter with the same blackout contract.
                Needed for the watchdog when ILDA hardware is present.
            require_watchdog: when ``True`` (the production default wired
                by :mod:`photonic_synesthesia.graph.builder`), raise
                :class:`ValueError` if neither ``dmx_output`` nor
                ``ilda_output`` was supplied. This closes the failure
                mode where a caller silently loses the dead-man switch
                by forgetting to wire an output.
                Tests that exercise the clamp/strobe logic without a
                watchdog can leave the flag at ``False``.
        """
        self.config = config
        self.fixtures = fixtures

        # Extract fixture info for safety checks
        self._laser_fixtures = [f for f in fixtures if f.type == "laser"]

        # Heartbeat tracking
        self._last_heartbeat = time.time()

        # Strobe rate tracking
        self._strobe_timestamps: deque = deque(maxlen=100)
        self._strobe_start_time: float | None = None
        self._in_cooldown = False
        self._cooldown_end: float = 0.0
        self._last_strobe_active = False
        self._strobe_channels = self._derive_strobe_channels()

        # Emergency stop state
        self._emergency_stop = False
        self._heartbeat_watchdog: HeartbeatWatchdog | None = None
        watchdog_callbacks = self._build_heartbeat_callbacks(dmx_output, ilda_output)
        if watchdog_callbacks:
            timeout_callback = self._make_heartbeat_callback(watchdog_callbacks)
            self._heartbeat_watchdog = HeartbeatWatchdog(
                on_timeout=timeout_callback,
                timeout_s=self.config.heartbeat_timeout_s,
            )
        elif require_watchdog:
            raise ValueError(
                "SafetyInterlockNode: require_watchdog=True but no dmx_output "
                "or ilda_output was provided; cannot install HeartbeatWatchdog. "
                "Production graphs must wire at least one output so the "
                "dead-man switch exists."
            )

    @staticmethod
    def _build_heartbeat_callbacks(
        *outputs: SupportsBlackout | SupportsEmergencyBlackout | None,
    ) -> list[Callable[[], None]]:
        """Resolve a stable callback list for emergency handling."""
        callbacks: list[Callable[[], None]] = []
        for output in outputs:
            if output is None:
                continue

            emergency_handler = getattr(output, "emergency_blackout", None)
            if callable(emergency_handler):
                callbacks.append(emergency_handler)
                continue

            request_handler = getattr(output, "request_blackout", None)
            if callable(request_handler):
                callbacks.append(request_handler)
                continue

            blackout_handler = getattr(output, "blackout", None)
            if callable(blackout_handler):
                callbacks.append(blackout_handler)

        return callbacks

    @staticmethod
    def _make_heartbeat_callback(callbacks: list[Callable[[], None]]) -> Callable[[], None]:
        def _on_timeout() -> None:
            for callback in callbacks:
                try:
                    callback()
                except Exception:
                    logger.exception("Emergency safety callback failed")

        return _on_timeout

    def start(self) -> None:
        """Start independent watchdog thread when available."""
        if self._heartbeat_watchdog is not None:
            self._heartbeat_watchdog.start()

    def stop(self) -> None:
        """Stop independent watchdog thread when available."""
        if self._heartbeat_watchdog is not None:
            self._heartbeat_watchdog.stop()

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
            universe = self._emergency_blackout()

        # Update heartbeat
        self._last_heartbeat = current_time
        if self._heartbeat_watchdog is not None:
            self._heartbeat_watchdog.beat()

        # =================================================================
        # Check 2: Emergency stop
        # =================================================================
        if self._emergency_stop:
            safety_ok = False
            error_state = "emergency_stop_active"
            universe = self._emergency_blackout()

        # =================================================================
        # Check 3: Laser Y-axis clamping
        # Applied to fixture_commands (current frame, before dmx_output) AND
        # to dmx_universe (previous frame snapshot, for defence-in-depth).
        # =================================================================
        for fixture in self._laser_fixtures:
            if not fixture.enabled:
                continue

            y_channel = fixture.start_address + self.config.laser.y_channel_offset
            speed_channel = fixture.start_address + self.config.laser.speed_channel_offset

            # --- Clamp current-frame fixture_commands ---
            for cmd in state["fixture_commands"]:
                if cmd.get("fixture_id") != fixture.id:
                    continue
                ch_vals = cmd["channel_values"]
                if y_channel in ch_vals and ch_vals[y_channel] > self.config.laser.y_axis_max:
                    ch_vals[y_channel] = self.config.laser.y_axis_max
                if (
                    speed_channel in ch_vals
                    and 0 < ch_vals[speed_channel] < self.config.laser.min_scan_speed
                ):
                    ch_vals[speed_channel] = self.config.laser.min_scan_speed

            # --- Clamp previous-frame dmx_universe (defence-in-depth) ---
            if is_valid_dmx_channel(y_channel):
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

            if is_valid_dmx_channel(speed_channel):
                current_speed = universe[speed_channel]
                min_speed = self.config.laser.min_scan_speed

                if current_speed < min_speed and current_speed > 0:
                    universe[speed_channel] = min_speed

        # =================================================================
        # Check 4: Strobe rate limiting and cooldown
        # =================================================================
        strobe_guard_reason = self._apply_strobe_guards(state, universe, current_time)
        if self._in_cooldown:
            safety_ok = False
            if error_state is None:
                error_state = strobe_guard_reason or "strobe_cooldown_active"

        # =================================================================
        # Check 5: Beat confidence threshold
        # =================================================================
        beat_confidence = state["beat_info"]["confidence"]
        if beat_confidence < self.config.min_beat_confidence:
            # Low confidence - reduce intensity to prevent random flashing
            if self.config.graceful_degradation:
                scale = self._apply_graceful_degradation(state, universe, beat_confidence)
                logger.debug(
                    "Applied graceful degradation",
                    beat_confidence=beat_confidence,
                    threshold=self.config.min_beat_confidence,
                    scale=scale,
                )

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

    def _emergency_blackout(self) -> bytearray:
        """Set all channels to zero."""
        return create_universe_buffer()

    def _derive_strobe_channels(self) -> set[int]:
        """
        Derive known strobe channels from fixture types.

        Current channel assumptions:
        - moving head strobe at base + 6
        - panel strobe at base + 4
        """
        channels: set[int] = set()
        for fixture in self.fixtures:
            if fixture.type == "moving_head":
                channels.add(fixture.start_address + 6)
            elif fixture.type == "panel":
                channels.add(fixture.start_address + 4)
        return channels

    def _apply_strobe_guards(
        self,
        state: PhotonicState,
        universe: bytearray,
        current_time: float,
    ) -> str | None:
        """
        Enforce strobe rate/duration limits and cooldown suppression.

        Returns a reason string when a cooldown state is active/triggered.
        """
        if not self._strobe_channels:
            self._last_strobe_active = False
            return None

        # Detect strobe activity from current command payload.
        command_active = False
        for cmd in state["fixture_commands"]:
            for channel, value in cmd["channel_values"].items():
                if channel in self._strobe_channels and value > 0:
                    command_active = True
                    break
            if command_active:
                break

        # If no command this frame, fall back to last committed universe state.
        universe_active = any(
            is_valid_dmx_channel(channel) and universe[channel] > 0 for channel in self._strobe_channels
        )
        strobe_active = command_active or universe_active

        if strobe_active and not self._last_strobe_active:
            self._strobe_timestamps.append(current_time)

        if strobe_active and self._strobe_start_time is None:
            self._strobe_start_time = current_time
        if not strobe_active:
            self._strobe_start_time = None

        # Keep only recent pulses in 1s window for rate estimates.
        while self._strobe_timestamps and (current_time - self._strobe_timestamps[0]) > 1.0:
            self._strobe_timestamps.popleft()

        reason: str | None = None
        if len(self._strobe_timestamps) > self.config.strobe.max_rate_hz:
            self._in_cooldown = True
            self._cooldown_end = current_time + self.config.strobe.cooldown_s
            self._strobe_start_time = None
            reason = "strobe_rate_limit_exceeded"
        elif (
            self._strobe_start_time is not None
            and (current_time - self._strobe_start_time) > self.config.strobe.max_duration_s
        ):
            self._in_cooldown = True
            self._cooldown_end = current_time + self.config.strobe.cooldown_s
            self._strobe_start_time = None
            reason = "strobe_duration_limit_exceeded"

        if self._in_cooldown:
            if current_time >= self._cooldown_end:
                self._in_cooldown = False
                self._strobe_timestamps.clear()
                reason = None
            else:
                # Force strobe outputs off during cooldown.
                for cmd in state["fixture_commands"]:
                    for channel in self._strobe_channels:
                        if channel in cmd["channel_values"]:
                            cmd["channel_values"][channel] = 0
                for channel in self._strobe_channels:
                    if is_valid_dmx_channel(channel):
                        universe[channel] = 0
                if reason is None:
                    reason = "strobe_cooldown_active"

        self._last_strobe_active = strobe_active
        return reason

    def _apply_graceful_degradation(
        self,
        state: PhotonicState,
        universe: bytearray,
        beat_confidence: float,
    ) -> float:
        """
        Reduce output intensity when beat confidence is low.

        This dampens abrupt/random lighting transitions while preserving mode and
        safety channels needed for stable fixture operation.
        """
        threshold = max(self.config.min_beat_confidence, 1e-6)
        ratio = max(0.0, min(1.0, beat_confidence / threshold))
        scale = max(0.35, ratio)
        if scale >= 0.999:
            return 1.0

        # Keep laser mode channels untouched to avoid dropping out of DMX mode.
        protected_channels = {fixture.start_address for fixture in self._laser_fixtures}

        for cmd in state["fixture_commands"]:
            for channel, value in list(cmd["channel_values"].items()):
                if channel in protected_channels or value <= 0:
                    continue
                cmd["channel_values"][channel] = int(max(0, min(255, value * scale)))

        for channel in range(1, len(universe)):
            if channel in protected_channels:
                continue
            value = universe[channel]
            if value > 0:
                universe[channel] = int(max(0, min(255, value * scale)))

        return scale

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
        dmx_output: SupportsBlackoutAndStats | None = None,
        ilda_output: SupportsBlackoutAndStats | None = None,
        check_interval: float = 0.1,
        max_silence: float = 1.0,
    ) -> None:
        if dmx_output is None and ilda_output is None:
            raise TypeError("SafetyMonitor requires at least one output to monitor")

        self._outputs: dict[str, SupportsBlackoutAndStats] = {}
        if dmx_output is not None:
            self._outputs["dmx"] = dmx_output
        if ilda_output is not None:
            self._outputs["ilda"] = ilda_output

        self.check_interval = max(check_interval, 0.01)
        self.max_silence = max(max_silence, 0.05)

        self._last_frame_count: dict[str, int] = dict.fromkeys(self._outputs, 0)
        self._last_check_time: dict[str, float] = {
            name: time.monotonic() for name in self._outputs
        }

        self._stop_signal = StopSignal()
        self._thread: threading.Thread | None = None
        self._last_stall_log: float = 0.0

    def start(self) -> None:
        """Start safety monitoring.

        Cycle-6 B1: refuses to double-start. A zombie SafetyMonitor
        would fire blackout callbacks twice per stall — safe against
        false positives but doubles the blackout-callback failure
        surface. Caller must fix the underlying leak instead.
        """
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError(
                "Safety-Monitor already running; refusing to double-start. "
                "A previous stop() likely left a zombie — see threadhygiene."
            )
        self._stop_signal.clear()
        self._thread = threading.Thread(
            target=self._monitor_loop,
            name="Safety-Monitor",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop safety monitoring. Raises if the monitor fails to exit."""
        self._stop_signal.stop()
        try:
            join_or_raise(self._thread, timeout=1.0, name="Safety-Monitor")
        finally:
            self._thread = None

    def _monitor_loop(self) -> None:
        """Monitor critical output health."""
        while not self._stop_signal.stopped():
            # Wake immediately on stop, not on the next sleep boundary.
            self._stop_signal.wait(self.check_interval)
            if self._stop_signal.stopped():
                break

            now = time.monotonic()
            stalled_outputs: list[str] = []

            for output_name, output in self._outputs.items():
                if not self._is_output_active(output):
                    self._last_frame_count[output_name] = self._safe_frame_count(
                        output,
                        self._last_frame_count[output_name],
                    )
                    self._last_check_time[output_name] = now
                    continue

                current_frames = self._safe_frame_count(
                    output,
                    self._last_frame_count[output_name],
                )

                if current_frames != self._last_frame_count[output_name]:
                    self._last_frame_count[output_name] = current_frames
                    self._last_check_time[output_name] = now
                    continue

                if now - self._last_check_time[output_name] > self.max_silence:
                    stalled_outputs.append(output_name)

            if stalled_outputs:
                self._trigger_blackout(stalled_outputs)
                if now - self._last_stall_log > max(self.check_interval, 1.0):
                    logger.critical(
                        "Output(s) stalled - triggering emergency blackout",
                        outputs=stalled_outputs,
                    )
                    self._last_stall_log = now

                for output_name in stalled_outputs:
                    output = self._outputs[output_name]
                    self._last_frame_count[output_name] = self._safe_frame_count(
                        output,
                        self._last_frame_count[output_name],
                    )

    @staticmethod
    def _build_output_blackout_callbacks(
        output: SupportsBlackoutAndStats,
    ) -> list[Callable[[], None]]:
        """Resolve emergency blackout callbacks with the safest method first."""
        callbacks: list[Callable[[], None]] = []
        emergency_handler = getattr(output, "emergency_blackout", None)
        if callable(emergency_handler):
            callbacks.append(emergency_handler)
            return callbacks

        request_handler = getattr(output, "request_blackout", None)
        if callable(request_handler):
            callbacks.append(request_handler)
            return callbacks

        blackout_handler = getattr(output, "blackout", None)
        if callable(blackout_handler):
            callbacks.append(blackout_handler)

        return callbacks

    def _is_output_active(self, output: SupportsBlackoutAndStats) -> bool:
        """Return False for outputs that are not currently running."""
        stats = output.get_stats()
        running = stats.get("running")
        if running is True:
            return True
        if running is False:
            return False

        # If running flag is absent, fall back to whether there are fixtures.
        fixture_count = stats.get("fixture_count")
        return not (isinstance(fixture_count, int) and fixture_count == 0)

    def _safe_frame_count(self, output: SupportsBlackoutAndStats, fallback: int) -> int:
        """Read frame counter from output stats with defensive defaults."""
        stats = output.get_stats()
        raw = stats.get("frames_sent")
        return raw if isinstance(raw, int) else fallback

    def _trigger_blackout(self, stalled_outputs: list[str]) -> None:
        """Apply emergency blackout across monitored outputs."""
        for output in self._outputs.values():
            handlers = self._build_output_blackout_callbacks(output)
            for callback in handlers:
                try:
                    callback()
                except Exception:
                    logger.exception("Safety monitor blackout callback failed")

        for output_name in stalled_outputs:
            logger.warning("Safety monitor detected stalled output", output=output_name)
