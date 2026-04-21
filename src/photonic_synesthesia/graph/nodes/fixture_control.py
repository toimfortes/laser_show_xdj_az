"""
Fixture Control Nodes: Generate DMX commands for specific fixture types.

Each fixture type (laser, moving head, LED panel) has its own control
logic that translates scene definitions and audio features into DMX values.
"""

from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any

from photonic_synesthesia.core.config import (
    FixtureConfig,
    LaserSafetyConfig,
    MovingHeadSafetyConfig,
)
from photonic_synesthesia.core.logging import get_logger
from photonic_synesthesia.core.state import FixtureCommand, MusicStructure, PhotonicState
from photonic_synesthesia.director.palettes import Palette, render_rgb, resolve_palette
from photonic_synesthesia.graph.nodes.section_dynamics import resolve_active_section_dynamics
from photonic_synesthesia.laser import build_laser_profiles
from photonic_synesthesia.platform.runtime_context import get_shared_playback_context

logger = get_logger(__name__)


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
        fixtures_dir: Path | None = None,
    ):
        self.fixtures = [f for f in fixtures if f.type == "laser"]
        self.safety = safety
        self.fixture_profiles = (
            build_laser_profiles(self.fixtures, fixtures_dir or Path("config/fixtures"))
            if self.fixtures
            else {}
        )

    def __call__(self, state: PhotonicState) -> PhotonicState:
        """Generate DMX commands for laser fixtures."""
        start_time = time.time()

        if not self.fixtures:
            return state

        dynamics = resolve_active_section_dynamics(state)
        if not dynamics["laser_enabled"]:
            for fixture in self.fixtures:
                if not fixture.enabled:
                    continue
                state["fixture_commands"].append(self._generate_disabled_laser_commands(fixture))
            state["processing_times"]["laser_control"] = time.time() - start_time
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
                motion_multiplier=dynamics["motion_multiplier"],
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
        *,
        motion_multiplier: float,
    ) -> FixtureCommand:
        """Generate DMX values for a single laser fixture."""
        base = fixture.start_address
        values: dict[int, int] = {}
        profile = self.fixture_profiles.get(fixture.id)
        channel_map = profile.channel_map if profile is not None else {}
        motion_gain = max(0.25, min(2.0, motion_multiplier))

        # Mode: force manual DMX range (commonly 200-255 for this fixture class)
        mode_channel = channel_map.get("mode")
        if mode_channel is not None:
            values[base + mode_channel] = 200

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

        pattern_channel = channel_map.get("pattern")
        if pattern_channel is not None:
            values[base + pattern_channel] = pattern * 4

        # =================================================================
        # X/Y position movement
        # =================================================================
        position_scale = 1.25 if profile and profile.control_surface == "ilda" else 1.0
        x_pos = int(128 + 100 * position_scale * math.sin(current_time * bpm / 60 * motion_gain))
        y_pos = int(64 + 30 * position_scale * math.sin(current_time * bpm / 120 * motion_gain))
        y_pos = min(y_pos, self.safety.y_axis_max)  # SAFETY: audience-height clamp

        x_channel = channel_map.get("x_pos")
        y_channel = channel_map.get("y_pos")
        if x_channel is not None:
            values[base + x_channel] = max(0, min(255, x_pos))
        if y_channel is not None:
            values[base + y_channel] = max(0, min(255, y_pos))

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
        pattern_speed = max(0, min(255, int(pattern_speed * (0.6 + motion_gain * 0.4))))

        scan_channel = channel_map.get("scan_speed")
        pattern_speed_channel = channel_map.get("pattern_speed")
        if scan_channel is not None:
            values[base + scan_channel] = max(0, min(255, scan_speed))
        if pattern_speed_channel is not None:
            values[base + pattern_speed_channel] = pattern_speed

        # =================================================================
        # Zoom modulation (beat/energy linked)
        # =================================================================
        if structure == MusicStructure.DROP:
            zoom = int(128 + 127 * math.sin(beat_phase * math.pi * 2))
        elif structure == MusicStructure.BUILDUP:
            zoom = int(64 + (128 * energy))
        else:
            zoom = int(64 + 32 * math.sin(current_time * 0.5))

        zoom_channel = channel_map.get("zoom")
        if zoom_channel is not None:
            values[base + zoom_channel] = zoom

        # =================================================================
        # Optional roll axes for hybrid/adapter fixtures
        # =================================================================
        if structure == MusicStructure.DROP:
            roll_speed = bpm / 60 * 3.0 * motion_gain
        elif structure == MusicStructure.BUILDUP:
            roll_speed = bpm / 60 * 1.5 * motion_gain
        else:
            roll_speed = bpm / 60 * 0.75 * motion_gain

        for axis_name, phase_offset in (("x_roll", 0.0), ("y_roll", 1.7), ("z_roll", 3.1)):
            axis_channel = channel_map.get(axis_name)
            if axis_channel is None:
                continue
            roll_value = int(128 + 110 * math.sin(current_time * roll_speed + phase_offset))
            values[base + axis_channel] = max(0, min(255, roll_value))

        return FixtureCommand(
            fixture_id=fixture.id,
            fixture_type="laser",
            channel_values=values,
        )

    def _generate_disabled_laser_commands(self, fixture: FixtureConfig) -> FixtureCommand:
        """Force mapped DMX laser channels into a neutral/off state."""
        base = fixture.start_address
        profile = self.fixture_profiles.get(fixture.id)
        channel_map = profile.channel_map if profile is not None else {}
        values = {
            base + channel_offset: 0
            for channel_offset in set(channel_map.values())
        }
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

        dynamics = resolve_active_section_dynamics(state)
        if not dynamics["movers_enabled"]:
            for fixture in self.fixtures:
                if not fixture.enabled:
                    continue
                state["fixture_commands"].append(self._generate_disabled_moving_head_commands(fixture))
            state["processing_times"]["moving_head_control"] = time.time() - start_time
            return state

        scene = state["scene_state"]["current_scene"]
        structure = state["current_structure"]
        beat_phase = state["beat_info"]["beat_phase"]
        bar_position = state["beat_info"]["bar_position"]
        bpm = state["fused_bpm"]
        energy = state["audio_features"]["rms_energy"]
        current_section = dynamics.get("current_section")
        program_look = self._current_program_look(current_section, state)
        director_state = state["director_state"]
        palette = resolve_palette(str(director_state.get("color_theme") or "neutral"))
        color_drive = float(director_state.get("color_drive") or 0.5)

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
                program_look=program_look,
                palette=palette,
                color_drive=color_drive,
                intensity_multiplier=dynamics["intensity_multiplier"],
                motion_multiplier=dynamics["motion_multiplier"],
                strobe_level=dynamics["strobe_level"] if dynamics.get("current_section") is not None else 1.0,
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
        *,
        program_look: dict[str, Any] | None = None,
        palette: Palette,
        color_drive: float,
        intensity_multiplier: float,
        motion_multiplier: float,
        strobe_level: float,
    ) -> FixtureCommand:
        """Generate DMX values for a single moving head."""
        base = fixture.start_address
        values: dict[int, int] = {}
        look_role = str(program_look.get("__role", "")) if isinstance(program_look, dict) else ""
        geometry_family = str(program_look.get("geometry_family", "")) if isinstance(program_look, dict) else ""
        color_mode = str(program_look.get("color_mode", "")) if isinstance(program_look, dict) else ""
        target_bias = str(program_look.get("target_bias", "")) if isinstance(program_look, dict) else ""
        motion_scale = max(0.35, min(2.0, float(program_look.get("motion", 1.0)))) if isinstance(program_look, dict) else 1.0
        motion_gain = max(0.25, min(2.0, motion_multiplier))
        effective_motion = max(0.25, min(2.5, motion_scale * motion_gain))
        intensity_gain = max(0.0, min(1.5, intensity_multiplier))
        strobe_gain = max(0.0, min(1.0, strobe_level))
        emphasis = max(0.0, min(1.0, float(program_look.get("emphasis", 0.5)))) if isinstance(program_look, dict) else 0.5
        mover_family = self._mover_family_for_program(structure, program_look)

        # =================================================================
        # Pan/Tilt - laser-synchronized motion families
        # =================================================================
        freq_x = bpm / 60 / 2  # Half-beat
        freq_y = bpm / 60 / 4  # Quarter-beat
        motion_phase = current_time * bpm / 60 * (0.7 + effective_motion * 0.9) + phase_offset
        beat_hit = 1.0 if beat_phase < 0.14 else 0.0
        pan_amp = 58 + effective_motion * 34 + emphasis * 18
        tilt_amp = 34 + effective_motion * 18 + emphasis * 10

        if mover_family == "hits":
            hit_gate = beat_hit * (0.75 + emphasis * 0.25)
            pan_norm = math.copysign(1.0, math.sin(motion_phase * 2.6)) * hit_gate
            tilt_norm = math.cos(motion_phase * 2.9) * hit_gate - (0.18 if target_bias == "crowd" else 0.05)
        elif mover_family == "cross":
            pan_norm = math.sin(motion_phase * 1.8)
            tilt_norm = math.sin(motion_phase * 0.9 + math.pi / 2) * 0.55
        elif mover_family == "rise":
            arc = max(-1.0, min(1.0, -0.72 + ((bar_position - 1) / 3.0) * 1.6))
            pan_norm = math.sin(motion_phase * 0.95) * 0.58
            tilt_norm = arc + math.sin(motion_phase * 0.42) * 0.18
        elif mover_family == "hold":
            pan_norm = math.sin(motion_phase * 0.25) * 0.08
            tilt_norm = -0.26 if target_bias == "crowd" else 0.18 if target_bias == "ceiling" else 0.0
        elif mover_family == "shape":
            pan_norm = math.sin(motion_phase * 0.92) * math.cos(motion_phase * 0.48)
            tilt_norm = math.cos(motion_phase * 0.7)
        else:
            pan_norm = math.sin(current_time * freq_x * effective_motion + phase_offset) * 0.82
            tilt_norm = math.cos(current_time * freq_y * effective_motion) * 0.72

        if target_bias == "crowd":
            tilt_norm -= 0.24
        elif target_bias == "ceiling":
            tilt_norm += 0.22

        pan = int(128 + pan_amp * max(-1.0, min(1.0, pan_norm)))
        tilt = int(128 + tilt_amp * max(-1.0, min(1.0, tilt_norm)))

        values[base + self.channel_map["pan"]] = pan
        values[base + self.channel_map["tilt"]] = tilt

        # Pan/tilt speed
        if mover_family == "hits":
            speed = 218
        elif mover_family == "cross":
            speed = 188
        elif mover_family == "rise":
            speed = 168
        elif mover_family == "hold":
            speed = 96
        else:
            speed = 200 if structure == MusicStructure.DROP else 128
        speed = max(0, min(255, int(round(speed * (0.65 + motion_gain * 0.35)))))
        values[base + self.channel_map["pan_tilt_speed"]] = speed

        # =================================================================
        # Dimmer - Energy linked
        # =================================================================
        role_boost = {
            "launch": 26,
            "fill": 34,
            "release": -30,
        }.get(look_role, 0)
        if structure == MusicStructure.DROP:
            dimmer = int(192 + 58 * energy + emphasis * 18 + role_boost)
        elif structure == MusicStructure.BREAKDOWN:
            dimmer = int(92 + 44 * energy + role_boost)
        else:
            dimmer = int(142 + 78 * energy + emphasis * 12 + role_boost)

        values[base + self.channel_map["dimmer"]] = max(0, min(255, int(round(dimmer * intensity_gain))))

        # =================================================================
        # Strobe - synced to fills / impacts
        # =================================================================
        if mover_family == "hits" and beat_hit > 0.0:
            strobe = 208
        elif look_role == "launch" and structure in {MusicStructure.DROP, MusicStructure.BUILDUP} and beat_hit > 0.0:
            strobe = 160
        else:
            strobe = 0

        values[base + self.channel_map["strobe"]] = (
            max(0, min(255, int(round(strobe * strobe_gain))))
            if strobe_gain > 0.0
            else 0
        )

        # =================================================================
        # Color wheel / RGB
        #
        # The palette comes from the director (director_state.color_theme);
        # the rendering style comes from the laser expression program
        # (color_mode). target_bias stays advisory for aim, not colour —
        # see the pan/tilt block above.
        #
        # When the expression picked "static" (or no explicit mode), the
        # laser side has a color_strategy fallback in ilda_output that
        # animates it anyway. The mover has no such fallback, so we
        # provide one here: on high-energy structures (drop/buildup),
        # default to beat-synced dual_cycle so the mover breathes with
        # the music instead of holding one hue for the whole phrase.
        # =================================================================
        mode_from_look = (color_mode or "").strip().lower()
        if mode_from_look in ("", "static"):
            if structure in (MusicStructure.DROP, MusicStructure.BUILDUP):
                effective_mode = "dual_cycle"
            elif structure == MusicStructure.BREAKDOWN:
                effective_mode = "morph"
            else:
                effective_mode = "static"
        else:
            effective_mode = mode_from_look

        # Beat-synced phase: one full cycle per 2 beats on drops/builds,
        # slower on calmer sections. phase_offset desynchronises multiple
        # movers for a wave effect.
        beats_per_cycle = 2.0 if structure in (MusicStructure.DROP, MusicStructure.BUILDUP) else 4.0
        beat_clock = bar_position + beat_phase
        phase = (beat_clock / beats_per_cycle) * 2.0 * math.pi + phase_offset

        rgb = render_rgb(
            palette,
            effective_mode,
            phase=phase,
            beat_hit=bool(beat_hit > 0.0),
            color_drive=color_drive,
        )
        values[base + self.channel_map["red"]] = rgb[0]
        values[base + self.channel_map["green"]] = rgb[1]
        values[base + self.channel_map["blue"]] = rgb[2]

        # Color wheel logic (fallback for non-RGB movers)
        # 0 is usually White/Open. We force it to 0 if RGB is used.
        # But if the user's movers only use the wheel, we should map the theme.
        color_wheel_val = 0
        if palette.name == "warm":
            color_wheel_val = 15  # Red
        elif palette.name == "cool":
            color_wheel_val = 60  # Blue
        elif palette.name == "poison":
            color_wheel_val = 45  # Green/Cyan
        elif palette.name == "cyan_magenta":
            color_wheel_val = 75  # Magenta
        elif palette.name == "deep_blue":
            color_wheel_val = 60  # Blue
        elif palette.name == "amber_cyan":
            color_wheel_val = 25  # Orange

        # If the mover is RGB-capable, color wheel MUST be 0 (Open).
        # We set both so it works on either fixture type.
        values[base + self.channel_map["color"]] = color_wheel_val if rgb[0] < 10 and rgb[1] < 10 and rgb[2] < 10 else 0

        # Gobo
        # =================================================================
        if mover_family == "hits":
            gobo = 0  # Open (solid beam)
        elif mover_family == "hold" or look_role == "release":
            gobo = 64  # Breakup pattern
        elif geometry_family in {"trace", "sheet"}:
            gobo = 72
        elif geometry_family in {"sequence", "scan", "rake"}:
            gobo = 32
        elif geometry_family in {"tunnel", "cone", "helix", "sky"}:
            gobo = 16
        else:
            gobo = 32  # Rotating pattern

        values[base + self.channel_map["gobo"]] = gobo

        return FixtureCommand(
            fixture_id=fixture.id,
            fixture_type="moving_head",
            channel_values=values,
        )

    def _generate_disabled_moving_head_commands(self, fixture: FixtureConfig) -> FixtureCommand:
        """Force moving-head channels to an explicit neutral/off state."""
        base = fixture.start_address
        values = {
            base + channel_offset: 0
            for channel_offset in set(self.channel_map.values())
        }
        return FixtureCommand(
            fixture_id=fixture.id,
            fixture_type="moving_head",
            channel_values=values,
        )

    def _current_program_look(
        self,
        current_section: dict[str, Any] | None,
        state: PhotonicState,
    ) -> dict[str, Any] | None:
        if not isinstance(current_section, dict):
            return None

        # Read only the playhead from the per-tick snapshot/global context.
        # Section selection itself comes from resolve_active_section_dynamics
        # so the mover path has a single source of truth for "active section".
        snapshot = dict(state.get("playback_snapshot") or {})
        if not snapshot:
            playback = get_shared_playback_context()
            if playback is None:
                return None
            snapshot = playback.snapshot()
        playhead = float(snapshot.get("playhead_seconds", 0.0))
        laser_program = current_section.get("laser_program")
        if not isinstance(laser_program, dict):
            return None

        start = float(current_section.get("start_seconds", 0.0))
        end = float(current_section.get("end_seconds", start + 1.0))
        progress = max(0.0, min(1.0, (playhead - start) / max(end - start, 1e-6)))
        role = str(laser_program.get("phrase_role", ""))
        director = state["director_state"]
        subphrase_role = str(director.get("subphrase_role", ""))
        fill_pressure = float(director.get("fill_pressure", 0.0))
        harmonic_tension = float(state["audio_features"]["harmonic_tension"])
        melodic_smoothness = float(director.get("melodic_smoothness", 0.0))
        windows = self._program_main_windows(laser_program)
        fills = [
            candidate
            for candidate in laser_program.get("fills") or []
            if isinstance(candidate, dict)
        ]
        selected = None
        selected_role = "sustain"
        selected_index = 0

        for window in windows:
            if window["start"] <= progress < window["end"] or (
                progress >= 0.999 and window is windows[-1]
            ):
                selected = dict(window["look"])
                selected_role = str(window["role"])
                selected_index = int(window["index"])
                break

        if selected is None and windows:
            fallback_window = windows[-1]
            selected = dict(fallback_window["look"])
            selected_role = str(fallback_window["role"])
            selected_index = int(fallback_window["index"])

        sustain_windows = [window for window in windows if window["role"] == "sustain"]
        if selected_role == "sustain" and sustain_windows:
            sustain_choice = max(0, min(len(sustain_windows) - 1, selected_index))
            if subphrase_role in {"variation", "pressure", "lift"} or harmonic_tension >= 0.58:
                sustain_choice = min(len(sustain_windows) - 1, sustain_choice + 1)
            elif subphrase_role in {"settle", "float"} or melodic_smoothness >= 0.7:
                sustain_choice = 0
            selected_window = sustain_windows[sustain_choice]
            selected = dict(selected_window["look"])
            selected_index = sustain_choice

        fill_every_bars = max(1, int(laser_program.get("fill_trigger_every_bars", 4)))
        total_main_bars = max(1, sum(int(window["bars"]) for window in windows))
        bars_elapsed = progress * total_main_bars
        if selected_role == "sustain" and fills and role in {"build_riser", "drop_launch", "drop_variation"}:
            fill_cycle = int(bars_elapsed // fill_every_bars)
            fill_index = (fill_cycle + selected_index + (1 if fill_pressure >= 0.72 else 0)) % len(fills)
            fill_look = fills[fill_index]
            fill_bars = max(1, int(fill_look.get("bars", 1)))
            cycle_progress = bars_elapsed - (fill_cycle * fill_every_bars)
            if cycle_progress < min(fill_bars, fill_every_bars):
                selected = dict(fill_look)
                selected_role = "fill"

        if selected is None:
            return None

        zone_policy = str(laser_program.get("zone_policy", ""))
        if zone_policy == "overhead_only":
            selected["target_bias"] = "ceiling"
        elif zone_policy == "overhead_bias" and selected.get("target_bias") == "crowd":
            selected["target_bias"] = "mid_air"
        elif zone_policy == "crowd_punctuate" and selected.get("target_bias") != "crowd" and progress > 0.2:
            selected["target_bias"] = "mid_air"
        selected["__role"] = selected_role
        return selected

    @staticmethod
    def _program_main_windows(laser_program: dict[str, Any]) -> list[dict[str, Any]]:
        windows: list[dict[str, Any]] = []

        def append_window(role: str, index: int, look: Any, fallback_bars: int) -> None:
            if not isinstance(look, dict):
                return
            bars = int(look.get("bars", fallback_bars))
            if role == "launch" and bars <= 0:
                return
            bars = max(1, bars) if role != "launch" else bars
            windows.append(
                {
                    "role": role,
                    "index": index,
                    "look": look,
                    "bars": bars,
                }
            )

        append_window("launch", 0, laser_program.get("launch"), 0)
        for index, look in enumerate(laser_program.get("sustain") or []):
            append_window("sustain", index, look, 4)
        append_window("release", 0, laser_program.get("release"), 4)

        total_bars = sum(int(window["bars"]) for window in windows)
        if total_bars <= 0:
            return []

        cursor = 0.0
        for window in windows:
            start = cursor / total_bars
            cursor += int(window["bars"])
            end = cursor / total_bars
            window["start"] = start
            window["end"] = end
        return windows

    @staticmethod
    def _mover_family_for_program(
        structure: MusicStructure,
        program_look: dict[str, Any] | None,
    ) -> str:
        if not isinstance(program_look, dict):
            if structure == MusicStructure.DROP:
                return "hits"
            if structure == MusicStructure.BREAKDOWN:
                return "hold"
            return "shape"

        role = str(program_look.get("__role", ""))
        geometry = str(program_look.get("geometry_family", ""))
        if role == "release":
            return "hold"
        if role == "fill":
            if geometry in {"burst", "grouped", "lattice", "array"}:
                return "hits"
            if geometry in {"sequence", "scan", "rake"}:
                return "cross"
            if geometry in {"tunnel", "cone", "helix", "sky"}:
                return "rise"
            return "shape"
        if role == "launch":
            if geometry in {"tunnel", "cone", "helix", "sky"}:
                return "rise"
            if geometry in {"trace", "sheet"}:
                return "shape"
            return "cross"
        if geometry in {"trace", "sheet"}:
            return "shape"
        if geometry in {"sequence", "scan", "rake", "lattice"}:
            return "cross"
        if geometry in {"tunnel", "cone", "helix", "sky"}:
            return "rise"
        if geometry in {"burst", "grouped", "array"}:
            return "hits"
        return "shape"


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

        dynamics = resolve_active_section_dynamics(state)
        panel_enabled = self._panel_enabled_for_dynamics(dynamics)
        if not panel_enabled:
            for fixture in self.fixtures:
                if not fixture.enabled:
                    continue
                state["fixture_commands"].append(self._generate_disabled_panel_commands(fixture))
            state["processing_times"]["panel_control"] = time.time() - start_time
            return state

        structure = state["current_structure"]
        beat_phase = state["beat_info"]["beat_phase"]
        bar_position = state["beat_info"]["bar_position"]
        energy = state["audio_features"]["rms_energy"]
        time_since_drop = state["time_since_last_drop"]
        director_state = state["director_state"]
        palette = resolve_palette(str(director_state.get("color_theme") or "neutral"))
        color_drive = float(director_state.get("color_drive") or 0.5)
        strobe_budget_hz = float(director_state.get("strobe_budget_hz") or 0.0)
        subphrase_role = str(director_state.get("subphrase_role") or "")

        for fixture in self.fixtures:
            if not fixture.enabled:
                continue

            commands = self._generate_panel_commands(
                fixture,
                structure,
                beat_phase,
                bar_position,
                energy,
                time_since_drop,
                state["timestamp"],
                palette=palette,
                color_drive=color_drive,
                strobe_budget_hz=strobe_budget_hz,
                subphrase_role=subphrase_role,
                intensity_multiplier=dynamics["intensity_multiplier"],
                motion_multiplier=dynamics["motion_multiplier"],
                strobe_level=dynamics["strobe_level"] if dynamics.get("current_section") is not None else 1.0,
            )

            state["fixture_commands"].append(commands)

        state["processing_times"]["panel_control"] = time.time() - start_time
        return state

    @staticmethod
    def _panel_enabled_for_dynamics(dynamics: dict[str, Any]) -> bool:
        """Resolve the per-tick panel gate from inferred family dynamics."""
        panel_family = dynamics.get("panel_family")
        if panel_family == "wash":
            return bool(dynamics["washes_enabled"])
        if panel_family == "led":
            return bool(dynamics["leds_enabled"])
        return bool(dynamics["washes_enabled"] or dynamics["leds_enabled"])

    def _generate_panel_commands(
        self,
        fixture: FixtureConfig,
        structure: MusicStructure,
        beat_phase: float,
        bar_position: int,
        energy: float,
        time_since_drop: float,
        current_time: float,
        *,
        palette: Palette,
        color_drive: float,
        strobe_budget_hz: float,
        subphrase_role: str,
        intensity_multiplier: float,
        motion_multiplier: float,
        strobe_level: float,
    ) -> FixtureCommand:
        """Generate DMX values for a single LED panel / bar.

        Color comes from the director's palette, animated beat-synced.
        Strobe is driven from the director's strobe_budget_hz (mapped
        onto the fixture's 1-240 strobe-rate range). The launch subphrase
        of each drop gets a short extra-fast blinder pulse on top of the
        baseline palette render.
        """
        base = fixture.start_address
        values: dict[int, int] = {}
        motion_gain = max(0.25, min(2.0, motion_multiplier))
        intensity_gain = max(0.0, min(1.5, intensity_multiplier))
        strobe_gain = max(0.0, min(1.0, strobe_level))

        # -- Baseline palette color, beat-synced dual_cycle on energy ---
        beats_per_cycle = (
            2.0 if structure in (MusicStructure.DROP, MusicStructure.BUILDUP) else 4.0
        ) / max(0.5, motion_gain)
        beat_clock = bar_position + beat_phase
        phase = (beat_clock / beats_per_cycle) * 2.0 * math.pi
        beat_hit = beat_phase < 0.15
        if structure in (MusicStructure.DROP, MusicStructure.BUILDUP):
            render_mode = "dual_cycle"
        elif structure == MusicStructure.BREAKDOWN:
            render_mode = "morph"
        else:
            render_mode = "static"
        rgb = render_rgb(
            palette,
            render_mode,
            phase=phase,
            beat_hit=beat_hit,
            color_drive=color_drive,
        )

        # -- Dimmer: energy + launch blinder ----------------------------
        if (
            structure == MusicStructure.DROP
            and subphrase_role == "launch"
            and time_since_drop < 0.9
        ):
            # Punch the dimmer to full so the launch blinder reads hard.
            dimmer = 255
            # Bias color toward accent (white on most palettes) for the
            # blinder hit. color_drive saturated.
            rgb = render_rgb(palette, "white_hits", phase=phase, beat_hit=True, color_drive=1.0)
        elif structure == MusicStructure.DROP:
            dimmer = int(200 + 55 * max(0.0, min(1.0, energy)))
        elif structure == MusicStructure.BUILDUP:
            dimmer = int(160 + 80 * max(0.0, min(1.0, energy)))
        elif structure == MusicStructure.BREAKDOWN:
            dimmer = int(90 + 60 * max(0.0, min(1.0, energy)))
        else:
            dimmer = int(60 + 120 * max(0.0, min(1.0, energy)))
        dimmer = int(dimmer * intensity_gain)

        # -- Strobe channel ----------------------------------------------
        # strobe_budget_hz is 0..~12 Hz from director. Map to the
        # fixture's standard strobe-rate band (DMX 16..240 is typical
        # "slow..fast"). Values below the cut-in threshold stay 0 so the
        # fixture is fully open rather than chattering at near-zero Hz.
        if strobe_gain <= 0.01 or strobe_budget_hz < 0.6:
            strobe_value = 0
        else:
            strobe_ratio = max(0.0, min(1.0, (strobe_budget_hz / 12.0) * strobe_gain))
            strobe_value = int(16 + round(strobe_ratio * (240 - 16)))
        values[base + self.channel_map["strobe"]] = strobe_value

        # No panel-specific nonzero mode contract exists in the repo, and the
        # pre-fix active path implicitly ran with the universe's zero-init
        # value. Write that value explicitly so active ticks recover from any
        # prior disable/garbage state instead of relying on universe history.
        values[base + self.channel_map["mode"]] = 0
        values[base + self.channel_map["dimmer"]] = max(0, min(255, dimmer))
        values[base + self.channel_map["red"]] = rgb[0]
        values[base + self.channel_map["green"]] = rgb[1]
        values[base + self.channel_map["blue"]] = rgb[2]

        return FixtureCommand(
            fixture_id=fixture.id,
            fixture_type="panel",
            channel_values=values,
        )

    def _generate_disabled_panel_commands(self, fixture: FixtureConfig) -> FixtureCommand:
        """Force mapped panel channels into a neutral/off state."""
        base = fixture.start_address
        values = {
            base + channel_offset: 0
            for channel_offset in set(self.channel_map.values())
        }
        return FixtureCommand(
            fixture_id=fixture.id,
            fixture_type="panel",
            channel_values=values,
        )
