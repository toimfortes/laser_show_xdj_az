"""
Fixture Control Nodes: Generate DMX commands for specific fixture types.

Each fixture type (laser, moving head, LED panel) has its own control
logic that translates scene definitions and audio features into DMX values.
"""

from __future__ import annotations

import time
import math
from typing import Dict, Any, List, Optional
import structlog

from photonic_synesthesia.core.state import PhotonicState, FixtureCommand, MusicStructure
from photonic_synesthesia.core.config import (
    FixtureConfig,
    LaserSafetyConfig,
    MovingHeadSafetyConfig,
)

logger = structlog.get_logger()


class LaserControlNode:
    """
    Controls laser fixtures based on scene and audio features.

    Implements:
    - Pattern selection
    - Zoom modulation (pumping effect)
    - Movement speed linked to energy
    - Color cycling
    - Safety limits (Y-axis clamping)
    """

    def __init__(
        self,
        fixtures: List[FixtureConfig],
        safety: LaserSafetyConfig,
    ):
        self.fixtures = [f for f in fixtures if f.type == "laser"]
        self.safety = safety

        # Standard 7-channel laser map
        self.channel_map = {
            "mode": 0,
            "pattern": 1,
            "zoom": 2,
            "x_roll": 3,
            "y_roll": 4,
            "movement": 5,
            "color": 6,
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
        values: Dict[int, int] = {}

        # Mode: Always DMX control (192-255)
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
        # Zoom modulation (pumping effect synced to beat)
        # =================================================================
        if structure == MusicStructure.DROP:
            # Aggressive pumping on beat
            zoom = int(128 + 127 * math.sin(beat_phase * math.pi * 2))
        elif structure == MusicStructure.BUILDUP:
            # Increasing intensity
            zoom = int(64 + (128 * energy))
        else:
            # Gentle oscillation
            zoom = int(64 + 32 * math.sin(current_time * 0.5))

        values[base + self.channel_map["zoom"]] = zoom

        # =================================================================
        # X/Y Roll - Movement patterns
        # =================================================================
        x_roll = int(128 + 100 * math.sin(current_time * bpm / 60))
        y_roll = int(64 + 30 * math.sin(current_time * bpm / 120))

        # SAFETY: Clamp Y-axis
        y_roll = min(y_roll, self.safety.y_axis_max)

        values[base + self.channel_map["x_roll"]] = x_roll
        values[base + self.channel_map["y_roll"]] = y_roll

        # =================================================================
        # Movement speed linked to energy
        # =================================================================
        if structure == MusicStructure.DROP:
            movement = int(180 + 75 * energy)
        elif structure == MusicStructure.BREAKDOWN:
            movement = self.safety.min_scan_speed
        else:
            movement = int(100 + 100 * energy)

        # SAFETY: Ensure minimum scan speed
        movement = max(movement, self.safety.min_scan_speed)

        values[base + self.channel_map["movement"]] = movement

        # =================================================================
        # Color based on energy/structure
        # =================================================================
        if structure == MusicStructure.DROP:
            # RGB strobe
            color = int((current_time * 10) % 255)
        elif structure == MusicStructure.BREAKDOWN:
            # Cool colors (blue/cyan)
            color = int(100 + 50 * math.sin(current_time * 0.2))
        else:
            # Warm colors (green/yellow)
            color = int(50 + 50 * math.sin(current_time * 0.3))

        values[base + self.channel_map["color"]] = color

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
        fixtures: List[FixtureConfig],
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
        values: Dict[int, int] = {}

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
            values[base + self.channel_map["green"]] = int(128 + 127 * math.sin(phase * math.pi * 2 + 2))
            values[base + self.channel_map["blue"]] = int(128 + 127 * math.sin(phase * math.pi * 2 + 4))

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

    def __init__(self, fixtures: List[FixtureConfig]):
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
        values: Dict[int, int] = {}

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
            values[base + self.channel_map["green"]] = int(100)
            values[base + self.channel_map["blue"]] = int(200 + 55 * math.sin(phase * math.pi * 2 + 1))
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
