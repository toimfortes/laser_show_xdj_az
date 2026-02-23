"""
Fixture Control Nodes: Generate DMX commands for specific fixture types.

Each fixture type (laser, moving head, LED panel) has its own control
logic that translates scene definitions and audio features into DMX values.
"""

from __future__ import annotations

import math
import time

import structlog

from photonic_synesthesia.core.config import (
    FixtureConfig,
    LaserSafetyConfig,
    MovingHeadSafetyConfig,
)
from photonic_synesthesia.core.state import FixtureCommand, MusicStructure, PhotonicState

logger = structlog.get_logger()


class LaserControlNode:
    """
    Controls laser fixtures based on scene and audio features.

    Implements:
    - Pattern selection
    - X/Y position movement
    - Scan speed and pattern play speed modulation
    - Zoom modulation (pumping effect)
    - Safety limits (Y-axis clamping)
    """

    def __init__(
        self,
        fixtures: list[FixtureConfig],
        safety: LaserSafetyConfig,
    ):
        self.fixtures = [f for f in fixtures if f.type == "laser"]
        self.safety = safety

        # OEM 7-channel laser map (common 4-lens RGBY units)
        self.channel_map = {
            "mode": 0,
            "pattern": 1,
            "x_pos": 2,
            "y_pos": 3,
            "scan_speed": 4,
            "pattern_speed": 5,
            "zoom": 6,
        }

    def __call__(self, state: PhotonicState) -> PhotonicState:
        """Generate DMX commands for laser fixtures."""
        start_time = time.time()

        if not self.fixtures:
            return state

        # Get current state
        scene = state["scene_state"]["current_scene"]
        structure = state["current_structure"]
        beat_phase = state["beat_info"]["beat_phase"]
        bpm = state["fused_bpm"]
        energy = state["audio_features"]["rms_energy"]
        low_energy = state["audio_features"]["low_energy"]

        for fixture in self.fixtures:
            if not fixture.enabled:
                continue

            commands = self._generate_laser_commands(
                fixture,
                scene,
                structure,
                beat_phase,
                bpm,
                energy,
                low_energy,
                state["timestamp"],
            )

            state["fixture_commands"].append(commands)

        state["processing_times"]["laser_control"] = time.time() - start_time
        return state

    def _generate_laser_commands(
        self,
        fixture: FixtureConfig,
        scene: str,
        structure: MusicStructure,
        beat_phase: float,
        bpm: float,
        energy: float,
        low_energy: float,
        current_time: float,
    ) -> FixtureCommand:
        """Generate DMX values for a single laser fixture."""
        base = fixture.start_address
        values: dict[int, int] = {}

        # Mode: force manual DMX range (commonly 200-255 for this fixture class)
        values[base + self.channel_map["mode"]] = 200

        # =================================================================
        # Pattern selection based on structure
        # =================================================================
        if structure == MusicStructure.DROP:
            pattern = int((current_time * 2) % 32)  # Fast pattern switching
        elif structure == MusicStructure.BUILDUP:
            pattern = 10  # Tunnel/cone pattern
        elif structure == MusicStructure.BREAKDOWN:
            pattern = 0  # Horizontal line (liquid sky)
        else:
            pattern = int((current_time * 0.5) % 16)  # Slow switching

        values[base + self.channel_map["pattern"]] = pattern * 4

        # =================================================================
        # X/Y position movement
        # =================================================================
        x_pos = int(128 + 100 * math.sin(current_time * bpm / 60))
        y_pos = int(64 + 30 * math.sin(current_time * bpm / 120))
        y_pos = min(y_pos, self.safety.y_axis_max)  # SAFETY: audience-height clamp

        values[base + self.channel_map["x_pos"]] = x_pos
        values[base + self.channel_map["y_pos"]] = y_pos

        # =================================================================
        # Scan speed and pattern play speed
        # =================================================================
        if structure == MusicStructure.DROP:
            scan_speed = int(170 + 70 * energy)
            pattern_speed = int(180 + 70 * energy)
        elif structure == MusicStructure.BREAKDOWN:
            scan_speed = self.safety.min_scan_speed
            pattern_speed = 60
        else:
            scan_speed = int(100 + 100 * energy)
            pattern_speed = int(80 + 120 * energy)

        # SAFETY: enforce configured lower bound until a fixture-specific polarity
        # check is completed during commissioning.
        scan_speed = max(scan_speed, self.safety.min_scan_speed)

        values[base + self.channel_map["scan_speed"]] = scan_speed
        values[base + self.channel_map["pattern_speed"]] = pattern_speed

        # =================================================================
        # Zoom modulation (beat/energy linked)
        # =================================================================
        if structure == MusicStructure.DROP:
            zoom = int(128 + 127 * math.sin(beat_phase * math.pi * 2))
        elif structure == MusicStructure.BUILDUP:
            zoom = int(64 + (128 * energy))
        else:
            zoom = int(64 + 32 * math.sin(current_time * 0.5))

        values[base + self.channel_map["zoom"]] = zoom

        return FixtureCommand(
            fixture_id=fixture.id,
            fixture_type="laser",
            channel_values=values,
        )


class MovingHeadControlNode:
    """
    Controls moving head fixtures with pan/tilt/color/gobo.

    Implements:
    - Lissajous movement patterns
    - Beat-synced tilt pulses
    - Color temperature mapping
    - Gobo selection based on structure
    """

    def __init__(
        self,
        fixtures: list[FixtureConfig],
        safety: MovingHeadSafetyConfig,
    ):
        self.fixtures = [f for f in fixtures if f.type == "moving_head"]
        self.safety = safety

        # Standard 16-channel moving head map
        self.channel_map = {
            "pan": 0,
            "pan_fine": 1,
            "tilt": 2,
            "tilt_fine": 3,
            "pan_tilt_speed": 4,
            "dimmer": 5,
            "strobe": 6,
            "color": 7,
            "gobo": 8,
            "gobo_rotation": 9,
            "prism": 10,
            "focus": 11,
            "frost": 12,
            "red": 13,
            "green": 14,
            "blue": 15,
        }

    def __call__(self, state: PhotonicState) -> PhotonicState:
        """Generate DMX commands for moving head fixtures."""
        start_time = time.time()

        if not self.fixtures:
            return state

        scene = state["scene_state"]["current_scene"]
        structure = state["current_structure"]
        beat_phase = state["beat_info"]["beat_phase"]
        bar_position = state["beat_info"]["bar_position"]
        bpm = state["fused_bpm"]
        energy = state["audio_features"]["rms_energy"]

        for i, fixture in enumerate(self.fixtures):
            if not fixture.enabled:
                continue

            # Offset phase for multiple fixtures
            phase_offset = (i / len(self.fixtures)) * math.pi * 2

            commands = self._generate_moving_head_commands(
                fixture,
                scene,
                structure,
                beat_phase,
                bar_position,
                bpm,
                energy,
                state["timestamp"],
                phase_offset,
            )

            state["fixture_commands"].append(commands)

        state["processing_times"]["moving_head_control"] = time.time() - start_time
        return state

    def _generate_moving_head_commands(
        self,
        fixture: FixtureConfig,
        scene: str,
        structure: MusicStructure,
        beat_phase: float,
        bar_position: int,
        bpm: float,
        energy: float,
        current_time: float,
        phase_offset: float,
    ) -> FixtureCommand:
        """Generate DMX values for a single moving head."""
        base = fixture.start_address
        values: dict[int, int] = {}

        # =================================================================
        # Pan/Tilt - Lissajous curves
        # =================================================================
        freq_x = bpm / 60 / 2  # Half-beat
        freq_y = bpm / 60 / 4  # Quarter-beat

        if structure == MusicStructure.DROP:
            # Fast chaotic movement
            pan = int(128 + 100 * math.sin(current_time * freq_x * 4 + phase_offset))
            tilt = int(128 + 60 * math.sin(current_time * freq_y * 4))
        elif structure == MusicStructure.BREAKDOWN:
            # Slow sweeping
            pan = int(128 + 120 * math.sin(current_time * 0.2 + phase_offset))
            tilt = int(100 + 30 * math.sin(current_time * 0.1))
        else:
            # Standard Lissajous
            pan = int(128 + 80 * math.sin(current_time * freq_x + phase_offset))
            tilt = int(128 + 50 * math.sin(current_time * freq_y))

        values[base + self.channel_map["pan"]] = pan
        values[base + self.channel_map["tilt"]] = tilt

        # Pan/tilt speed
        speed = 200 if structure == MusicStructure.DROP else 128
        values[base + self.channel_map["pan_tilt_speed"]] = speed

        # =================================================================
        # Dimmer - Energy linked
        # =================================================================
        if structure == MusicStructure.DROP:
            dimmer = int(200 + 55 * energy)
        elif structure == MusicStructure.BREAKDOWN:
            dimmer = int(100 + 50 * energy)
        else:
            dimmer = int(150 + 80 * energy)

        values[base + self.channel_map["dimmer"]] = min(255, dimmer)

        # =================================================================
        # Strobe - Beat synced during drops
        # =================================================================
        if structure == MusicStructure.DROP and beat_phase < 0.1:
            strobe = 200  # Fast strobe on beat
        else:
            strobe = 0  # No strobe

        values[base + self.channel_map["strobe"]] = strobe

        # =================================================================
        # Color wheel / RGB
        # =================================================================
        if structure == MusicStructure.DROP:
            values[base + self.channel_map["red"]] = 255
            values[base + self.channel_map["green"]] = 255
            values[base + self.channel_map["blue"]] = 255
        elif structure == MusicStructure.BREAKDOWN:
            values[base + self.channel_map["red"]] = 50
            values[base + self.channel_map["green"]] = 100
            values[base + self.channel_map["blue"]] = 255
        else:
            phase = (current_time * 0.2) % 1
            values[base + self.channel_map["red"]] = int(128 + 127 * math.sin(phase * math.pi * 2))
            values[base + self.channel_map["green"]] = int(
                128 + 127 * math.sin(phase * math.pi * 2 + 2)
            )
            values[base + self.channel_map["blue"]] = int(
                128 + 127 * math.sin(phase * math.pi * 2 + 4)
            )

        # =================================================================
        # Gobo
        # =================================================================
        if structure == MusicStructure.DROP:
            gobo = 0  # Open (solid beam)
        elif structure == MusicStructure.BREAKDOWN:
            gobo = 64  # Breakup pattern
        else:
            gobo = 32  # Rotating pattern

        values[base + self.channel_map["gobo"]] = gobo

        return FixtureCommand(
            fixture_id=fixture.id,
            fixture_type="moving_head",
            channel_values=values,
        )


class PanelControlNode:
    """
    Controls LED panel fixtures.

    Implements:
    - Solid colors
    - Strobe effects
    - Energy-linked brightness
    - Blinder effects on drops
    """

    def __init__(self, fixtures: list[FixtureConfig]):
        self.fixtures = [f for f in fixtures if f.type == "panel"]

        # Simple RGB panel map
        self.channel_map = {
            "dimmer": 0,
            "red": 1,
            "green": 2,
            "blue": 3,
            "strobe": 4,
            "mode": 5,
        }

    def __call__(self, state: PhotonicState) -> PhotonicState:
        """Generate DMX commands for LED panels."""
        start_time = time.time()

        if not self.fixtures:
            return state

        structure = state["current_structure"]
        beat_phase = state["beat_info"]["beat_phase"]
        energy = state["audio_features"]["rms_energy"]
        time_since_drop = state["time_since_last_drop"]

        for fixture in self.fixtures:
            if not fixture.enabled:
                continue

            commands = self._generate_panel_commands(
                fixture,
                structure,
                beat_phase,
                energy,
                time_since_drop,
                state["timestamp"],
            )

            state["fixture_commands"].append(commands)

        state["processing_times"]["panel_control"] = time.time() - start_time
        return state

    def _generate_panel_commands(
        self,
        fixture: FixtureConfig,
        structure: MusicStructure,
        beat_phase: float,
        energy: float,
        time_since_drop: float,
        current_time: float,
    ) -> FixtureCommand:
        """Generate DMX values for a single LED panel."""
        base = fixture.start_address
        values: dict[int, int] = {}

        # =================================================================
        # Blinder effect on drop
        # =================================================================
        if structure == MusicStructure.DROP and time_since_drop < 0.5:
            # Full white blinder
            values[base + self.channel_map["dimmer"]] = 255
            values[base + self.channel_map["red"]] = 255
            values[base + self.channel_map["green"]] = 255
            values[base + self.channel_map["blue"]] = 255
            values[base + self.channel_map["strobe"]] = 0

        elif structure == MusicStructure.DROP:
            # Beat-synced strobe
            if beat_phase < 0.15:
                values[base + self.channel_map["dimmer"]] = 255
                values[base + self.channel_map["red"]] = 255
                values[base + self.channel_map["green"]] = 255
                values[base + self.channel_map["blue"]] = 255
            else:
                values[base + self.channel_map["dimmer"]] = 0
                values[base + self.channel_map["red"]] = 0
                values[base + self.channel_map["green"]] = 0
                values[base + self.channel_map["blue"]] = 0
            values[base + self.channel_map["strobe"]] = 0

        elif structure == MusicStructure.BREAKDOWN:
            # Slow color wash
            phase = (current_time * 0.1) % 1
            values[base + self.channel_map["dimmer"]] = int(100 + 50 * energy)
            values[base + self.channel_map["red"]] = int(50 + 50 * math.sin(phase * math.pi * 2))
            values[base + self.channel_map["green"]] = 100
            values[base + self.channel_map["blue"]] = int(
                200 + 55 * math.sin(phase * math.pi * 2 + 1)
            )
            values[base + self.channel_map["strobe"]] = 0

        else:
            # Energy-linked ambient
            values[base + self.channel_map["dimmer"]] = int(150 * energy + 50)
            values[base + self.channel_map["red"]] = 200
            values[base + self.channel_map["green"]] = 150
            values[base + self.channel_map["blue"]] = 100
            values[base + self.channel_map["strobe"]] = 0

        return FixtureCommand(
            fixture_id=fixture.id,
            fixture_type="panel",
            channel_values=values,
        )
