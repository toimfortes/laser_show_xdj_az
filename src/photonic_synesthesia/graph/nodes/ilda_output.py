"""ILDA frame generation node for hybrid laser fixtures."""

from __future__ import annotations

import json
import math
import threading
import time
from pathlib import Path
from typing import Any

from photonic_synesthesia.core.config import FixtureConfig, ILDAConfig, LaserSafetyConfig
from photonic_synesthesia.core.logging import get_logger
from photonic_synesthesia.core.state import ILDAFrame, ILDAPoint, MusicStructure, PhotonicState
from photonic_synesthesia.director.palettes import (
    DEFAULT_PALETTE,
    Palette,
    render_rgb,
    resolve_palette,
)
from photonic_synesthesia.laser import build_laser_profiles
from photonic_synesthesia.laser.ether_dream import EtherDreamClient
from photonic_synesthesia.laser.ilda_file import encode_ild
from photonic_synesthesia.platform.runtime_context import get_shared_playback_context

logger = get_logger(__name__)

_ILDA_MIN = -32767
_ILDA_MAX = 32767


def _clamp_coord(value: float) -> int:
    return max(_ILDA_MIN, min(_ILDA_MAX, int(value)))


def _rgb_from_mode(
    color_mode: str,
    phase: float,
    color_drive: float,
    harshness: float,
    palette: Palette | None = None,
) -> tuple[int, int, int]:
    """Render a laser RGB from (color_mode style × palette hue set).

    When ``palette`` is provided, the director's color theme drives the
    hue selection and ``color_mode`` is just the rendering style. When
    absent (legacy callers / tests), falls back to the neutral palette.
    ``harshness`` feeds into ``white_hits`` brightness biasing.
    """
    effective_palette = palette if palette is not None else DEFAULT_PALETTE
    drive_bias = max(0.0, min(1.0, color_drive + harshness * 0.25))
    return render_rgb(
        effective_palette,
        color_mode,
        phase=phase,
        beat_hit=False,
        color_drive=drive_bias,
    )


def _program_color_mode(color_mode: str | None, color_strategy: str | None, fallback: str) -> str:
    if color_mode:
        return color_mode
    if color_strategy in {"white_accent_launch"}:
        return "white_hits"
    if color_strategy in {"contrast_flips", "dual_cycle_contrast", "target_color_steps", "texture_flip"}:
        return "dual_cycle"
    if color_strategy in {"single_hue_focus"}:
        return "static"
    if color_strategy:
        return "morph"
    return fallback


class ILDAOutputNode:
    """Generate ILDA point frames for fixtures whose primary surface is ILDA."""

    def __init__(
        self,
        config: ILDAConfig,
        fixtures: list[FixtureConfig],
        safety: LaserSafetyConfig,
        fixtures_dir: Path,
    ) -> None:
        self.config = config
        self.safety = safety
        self.fixture_profiles = build_laser_profiles(fixtures, fixtures_dir)
        self.fixtures = [
            fixture
            for fixture in fixtures
            if fixture.type == "laser"
            and fixture.id in self.fixture_profiles
            and self.fixture_profiles[fixture.id].control_surface == "ilda"
        ]
        self._running = False
        self._export_path = config.export_path
        self._ild_timeline: list[ILDAFrame] = []
        self._blackout_requested = False

    def start(self) -> None:
        self._running = True
        self._ild_timeline = []
        self._blackout_requested = False
        if self.config.transport_type == "json" and self._export_path is not None:
            self._export_path.parent.mkdir(parents=True, exist_ok=True)
        if self.config.transport_type == "ild" and self._export_path is not None:
            self._export_path.parent.mkdir(parents=True, exist_ok=True)

    def stop(self) -> None:
        self._ild_timeline = []
        self._blackout_requested = False
        self._running = False

    def request_blackout(self) -> None:
        self._blackout_requested = True

    def emergency_blackout(self) -> None:
        self._blackout_requested = True

    def clear_blackout_request(self) -> None:
        self._blackout_requested = False

    @property
    def fixture_count(self) -> int:
        return len(self.fixtures)

    @staticmethod
    def _blank_point_frame() -> ILDAFrame:
        return ILDAFrame(
            fixture_id="ilda-blank-fallback",
            profile_name="ilda-blank",
            geometry_family="blank",
            color_mode="off",
            target_bias="mixed",
            point_count=2,
            repeat=True,
            points=[
                ILDAPoint(x=0, y=0, r=0, g=0, b=0, blanked=True),
                ILDAPoint(x=0, y=0, r=0, g=0, b=0, blanked=True),
            ],
        )

    def __call__(self, state: PhotonicState) -> PhotonicState:
        start_time = time.time()
        if not self.config.enabled or not self.fixtures:
            state["ilda_frames"] = []
            state["processing_times"]["ilda_output"] = time.time() - start_time
            return state

        if self._should_blackout(state):
            frames = [self._blank_frame_for_fixture(fixture) for fixture in self.fixtures]
        else:
            frames = [self._frame_for_fixture(fixture, state) for fixture in self.fixtures]
        state["ilda_frames"] = frames
        self._export_frames(frames)
        state["processing_times"]["ilda_output"] = time.time() - start_time
        return state

    def get_stats(self) -> dict[str, int | float | bool | str | None]:
        return {
            "running": self._running,
            "fixture_count": len(self.fixtures),
            "points_per_frame": self.config.points_per_frame,
            "transport_type": self.config.transport_type,
            "export_path": str(self._export_path) if self._export_path else None,
        }

    def _should_blackout(self, state: PhotonicState) -> bool:
        control_state = state["control_state"]
        safety_state = state["safety_state"]
        return bool(
            self._blackout_requested
            or not control_state["armed_live"]
            or control_state["blackout_active"]
            or safety_state["emergency_stop"]
            or not safety_state["laser_enabled"]
        )

    def _blank_frame_for_fixture(self, fixture: FixtureConfig) -> ILDAFrame:
        profile = self.fixture_profiles[fixture.id]
        return ILDAFrame(
            fixture_id=fixture.id,
            profile_name=profile.profile_name,
            geometry_family="blank",
            color_mode="off",
            target_bias="mixed",
            point_count=2,
            repeat=True,
            points=[
                ILDAPoint(x=0, y=0, r=0, g=0, b=0, blanked=True),
                ILDAPoint(x=0, y=0, r=0, g=0, b=0, blanked=True),
            ],
        )

    def _frame_for_fixture(self, fixture: FixtureConfig, state: PhotonicState) -> ILDAFrame:
        profile = self.fixture_profiles[fixture.id]
        structure = state["current_structure"]
        beat_phase = state["beat_info"]["beat_phase"]
        bpm = state["fused_bpm"]
        timestamp = state["timestamp"]
        audio = state["audio_features"]
        director = state["director_state"]
        program_look = self._current_program_look(state)

        geometry_family = (
            str(program_look.get("geometry_family"))
            if program_look is not None and program_look.get("geometry_family")
            else self._geometry_family(structure, director["laser_aggression"])
        )
        color_mode = _program_color_mode(
            str(program_look.get("color_mode")) if program_look is not None and program_look.get("color_mode") else None,
            str(program_look.get("color_strategy")) if program_look is not None and program_look.get("color_strategy") else None,
            self._color_mode(director["color_drive"], audio["timbral_harshness"]),
        )
        target_bias = (
            str(program_look.get("target_bias"))
            if program_look is not None and program_look.get("target_bias")
            else self._target_bias(
                director["melodic_smoothness"],
                director["laser_aggression"],
                structure,
            )
        )
        palette = resolve_palette(str(director.get("color_theme") or "neutral"))
        points = self._build_points(
            point_count=max(24, self.config.points_per_frame),
            geometry_family=geometry_family,
            color_mode=color_mode,
            target_bias=target_bias,
            beat_phase=beat_phase,
            bpm=bpm,
            timestamp=timestamp,
            harmonic_change=audio["harmonic_change"],
            pitch_height=audio["pitch_height"],
            melodic_contour=audio["melodic_contour"],
            melodic_stability=audio["melodic_stability"],
            onset_density=audio["onset_density"],
            harmonic_tension=audio["harmonic_tension"],
            harshness=audio["timbral_harshness"],
            color_drive=director["color_drive"],
            aggression=director["laser_aggression"],
            melodic_smoothness=director["melodic_smoothness"],
            motion_energy=director["laser_motion_energy"],
            color_energy=director["laser_color_energy"],
            program_look=program_look,
            palette=palette,
        )
        return ILDAFrame(
            fixture_id=fixture.id,
            profile_name=profile.profile_name,
            geometry_family=geometry_family,
            color_mode=color_mode,
            target_bias=target_bias,
            point_count=len(points),
            repeat=True,
            points=points,
        )

    def _current_program_look(self, state: PhotonicState) -> dict[str, Any] | None:
        playback = get_shared_playback_context()
        if playback is None:
            return None
        snapshot = playback.snapshot()
        sections = snapshot.get("show_sections") or []
        if not sections:
            return None
        playhead = float(snapshot.get("playhead_seconds", 0.0))
        current_section = None
        for section in sections:
            start = float(section.get("start_seconds", 0.0))
            end = float(section.get("end_seconds", start))
            if start <= playhead < max(end, start + 1e-6):
                current_section = section
                break
        if current_section is None:
            current_section = sections[-1]
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
    def _geometry_family(structure: MusicStructure, aggression: float) -> str:
        if structure == MusicStructure.DROP:
            return "burst" if aggression > 0.7 else "lattice"
        if structure == MusicStructure.BUILDUP:
            return "rake"
        if structure == MusicStructure.BREAKDOWN:
            return "sky"
        if aggression > 0.55:
            return "helix"
        return "fan"

    @staticmethod
    def _color_mode(color_drive: float, harshness: float) -> str:
        if harshness > 0.72:
            return "white_hits"
        if color_drive > 0.62:
            return "morph"
        if color_drive > 0.34:
            return "dual_cycle"
        return "static"

    @staticmethod
    def _target_bias(
        melodic_smoothness: float,
        aggression: float,
        structure: MusicStructure,
    ) -> str:
        if structure == MusicStructure.BREAKDOWN or melodic_smoothness > 0.7:
            return "ceiling"
        if aggression > 0.68 or structure == MusicStructure.DROP:
            return "crowd"
        return "mid_air"

    def _build_points(
        self,
        *,
        point_count: int,
        geometry_family: str,
        color_mode: str,
        target_bias: str,
        beat_phase: float,
        bpm: float,
        timestamp: float,
        harmonic_change: float,
        pitch_height: float,
        melodic_contour: float,
        melodic_stability: float,
        onset_density: float,
        harmonic_tension: float,
        harshness: float,
        color_drive: float,
        aggression: float,
        melodic_smoothness: float,
        motion_energy: float,
        color_energy: float,
        program_look: dict[str, Any] | None,
        palette: Palette = DEFAULT_PALETTE,
    ) -> list[ILDAPoint]:
        sweep_phase = timestamp * max(0.25, bpm / 60.0) * (0.5 + aggression * 1.8)
        density_scale = float(program_look.get("density", 1.0)) if program_look else 1.0
        motion_scale = float(program_look.get("motion", 1.0)) if program_look else 1.0
        amplitude_x = (0.35 + aggression * 0.45) * (0.78 + motion_scale * 0.34) * (0.86 + motion_energy * 0.28)
        amplitude_y = min(
            self.safety.y_axis_max / 255.0,
            (0.12 + melodic_smoothness * 0.28 + pitch_height * 0.18 + (melodic_contour - 0.5) * 0.08)
            * (0.82 + motion_scale * 0.22),
        )
        if geometry_family == "burst":
            amplitude_x += 0.08
            amplitude_y += 0.04
        elif geometry_family == "sky":
            amplitude_y += 0.12
        elif geometry_family == "rake":
            amplitude_x *= 0.8
            amplitude_y += 0.08
        elif geometry_family == "array":
            amplitude_x *= 0.68
            amplitude_y *= 0.65
        elif geometry_family == "sheet":
            amplitude_x *= 1.08
            amplitude_y *= 0.45
        elif geometry_family == "trace":
            amplitude_x *= 0.74
            amplitude_y *= 0.72
        elif geometry_family == "sequence":
            amplitude_x *= 0.82
            amplitude_y *= 0.58

        y_offset = {
            "crowd": -0.2,
            "mid_air": 0.05,
            "ceiling": 0.28,
        }[target_bias]
        y_offset = min(y_offset, (self.safety.y_axis_max / 255.0) - amplitude_y)
        beat_boost = 1.0 + (0.18 + onset_density * 0.18) * math.sin(beat_phase * math.pi * 2.0)
        points: list[ILDAPoint] = []
        for index in range(point_count):
            t = index / max(1, point_count - 1)
            shape_phase = sweep_phase + t * math.pi * 2.0
            if geometry_family == "fan":
                x = math.sin(shape_phase) * amplitude_x * beat_boost
                y = y_offset + math.cos(shape_phase * 0.5) * amplitude_y
            elif geometry_family == "burst":
                radial = (0.15 + 0.85 * t) * beat_boost
                x = math.sin(shape_phase * 1.8) * amplitude_x * radial
                y = y_offset + math.cos(shape_phase * 1.1) * amplitude_y * radial
            elif geometry_family == "lattice":
                x = math.sin(shape_phase * 2.0) * amplitude_x
                y = y_offset + math.sin(shape_phase * 3.0 + harmonic_change * 3.0) * amplitude_y
            elif geometry_family == "rake":
                x = (-amplitude_x + 2 * amplitude_x * t) * beat_boost
                y = y_offset + math.sin(sweep_phase + t * math.pi * 4.0) * amplitude_y
            elif geometry_family == "helix":
                x = math.sin(shape_phase * 1.3) * amplitude_x
                y = y_offset + math.cos(shape_phase * 1.9) * amplitude_y
            elif geometry_family == "array":
                lane = (index % 4) / 3.0 - 0.5
                x = lane * amplitude_x * 1.6 + math.sin(sweep_phase + (index // 4) * 0.35) * amplitude_x * 0.12
                y = y_offset + math.cos(shape_phase * 0.7) * amplitude_y * 0.55
            elif geometry_family == "sheet":
                x = (-amplitude_x + 2 * amplitude_x * t)
                y = y_offset + math.sin(sweep_phase * 0.5) * amplitude_y * 0.18
            elif geometry_family == "trace":
                radius = 0.45 + 0.25 * math.sin(sweep_phase * 0.6)
                x = math.cos(shape_phase * (1.0 + melodic_stability * 0.6)) * amplitude_x * radius
                y = y_offset + math.sin(shape_phase * (1.0 + harmonic_tension * 0.8)) * amplitude_y * radius
            elif geometry_family == "sequence":
                lane_count = 5
                lane = (index % lane_count) / max(1, lane_count - 1) - 0.5
                x = lane * amplitude_x * 1.5
                y = y_offset + math.sin(sweep_phase + (index // lane_count) * 0.65) * amplitude_y * 0.5
            else:
                x = math.sin(shape_phase * 0.7) * amplitude_x * 0.75
                y = y_offset + abs(math.sin(shape_phase * 0.9)) * amplitude_y

            color_phase = shape_phase + harmonic_change * 5.0 + color_energy * 2.0
            r, g, b = _rgb_from_mode(
                color_mode,
                color_phase,
                color_drive + color_energy * 0.25,
                harshness,
                palette=palette,
            )
            blanked = False
            blanking_density = max(1, int(round(8 - min(6, density_scale * 3.2))))
            if geometry_family == "burst" and aggression > 0.72:
                blanked = (index % 5) in {0, 1} and beat_phase < 0.22
            elif geometry_family == "sequence":
                blanked = (index % blanking_density) != int((beat_phase * blanking_density) % blanking_density)
            elif geometry_family == "sheet":
                blanked = density_scale < 0.9 and (index % max(2, blanking_density - 2)) == 0
            elif harshness > 0.78:
                blanked = (index % 7) == 0 and math.sin(shape_phase * 2.0) > 0.0

            points.append(
                ILDAPoint(
                    x=_clamp_coord(x * _ILDA_MAX),
                    y=_clamp_coord(y * _ILDA_MAX),
                    r=0 if blanked else r,
                    g=0 if blanked else g,
                    b=0 if blanked else b,
                    blanked=blanked,
                )
            )
        return points

    def _export_frames(self, frames: list[ILDAFrame]) -> None:
        if self.config.transport_type == "memory":
            return
        if self.config.transport_type == "json":
            if self._export_path is None:
                return
            payload = {
                "generated_at": time.time(),
                "frames": frames,
            }
            self._export_path.write_text(json.dumps(payload), encoding="utf-8")
            return
        if self.config.transport_type == "ild":
            if self._export_path is None:
                return
            self._ild_timeline.extend(frames)
            self._export_path.write_bytes(encode_ild(self._ild_timeline))
            return


class ILDADACOutputNode:
    """Transmit ILDA frames to Ether Dream hardware outputs."""

    def __init__(
        self,
        config: ILDAConfig,
        safety: LaserSafetyConfig,
        fixtures: list[FixtureConfig],
    ) -> None:
        self.config = config
        self.safety = safety
        self.ilda_fixtures = [
            fixture
            for fixture in fixtures
            if fixture.type == "laser" and fixture.enabled
        ]
        self._running = False
        self._ether_dream: EtherDreamClient | None = None
        self._ether_dream_faulted = False
        self._blackout_requested = False
        self._emergency_until = 0.0
        self._transport_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._thread_stop = threading.Event()
        self._state_frames_sent = 0

    def start(self) -> None:
        self._running = True
        self._ether_dream_faulted = False
        self._blackout_requested = False
        self._thread_stop.clear()
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(
                target=self._emergency_loop,
                name="ILDA-Emergency-Output",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        self._running = False
        self._thread_stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        self._clear_emergency()

        client = self._ether_dream
        if client is not None:
            try:
                client.stop()
                client.close()
            except OSError:
                logger.warning("Failed to close Ether Dream connection cleanly")
            finally:
                self._ether_dream = None

        self._blackout_requested = False
        self._emergency_until = 0.0

    def request_blackout(self) -> None:
        self._blackout_requested = True

    def emergency_blackout(self) -> None:
        self._blackout_requested = True
        self._emergency_until = time.monotonic() + self.safety.ilda_blackout_hold_s
        self._send_emergency_stop()

    def blackout(self) -> None:
        self.emergency_blackout()

    def clear_blackout_request(self) -> None:
        self._blackout_requested = False
        self._emergency_until = 0.0
        self._clear_emergency()

    def _clear_emergency(self) -> None:
        client = self._ether_dream
        if client is None:
            return
        try:
            client.clear_emergency_stop()
        except OSError:
            logger.debug("Failed to clear Ether Dream emergency stop", exc_info=True)

    def _send_emergency_stop(self) -> None:
        client = self._ether_dream
        if client is None:
            try:
                client = self._ensure_ether_dream_client()
            except OSError:
                return
        try:
            client.emergency_stop()
        except OSError as exc:
            self._handle_ether_dream_error(exc)

    def _stream_emergency_blank_frame(self) -> None:
        try:
            self._send_emergency_stop()
            blank_frame = self._build_blank_dac_frame()
            self._stream_frames(blank_frame)
        except OSError:
            logger.debug("Ether Dream emergency transmission failed", exc_info=True)

    def get_stats(self) -> dict[str, int | float | bool | str | None]:
        return {
            "running": self._running,
            "transport_type": self.config.transport_type,
            "ether_dream_host": self.config.ether_dream_host,
            "ether_dream_port": self.config.ether_dream_port,
            "ether_dream_faulted": self._ether_dream_faulted,
            "fixture_count": len(self.ilda_fixtures),
            "frames_sent": self._state_frames_sent,
        }

    @property
    def fixture_count(self) -> int:
        return len(self.ilda_fixtures)

    def __call__(self, state: PhotonicState) -> PhotonicState:
        start_time = time.time()
        if (
            self.config.transport_type != "ether_dream"
            or not self.config.enabled
            or not self.ilda_fixtures
            or not state["ilda_frames"]
        ):
            state["processing_times"]["ilda_output"] = time.time() - start_time
            return state

        if self._blackout_requested:
            frames = [self._blank_frame_for_fixture(fixture) for fixture in self.ilda_fixtures]
            self._stream_frames(self._merge_frames_for_dac(frames))
        else:
            self._stream_frames(self._merge_frames_for_dac(state["ilda_frames"]))

        state["processing_times"]["ilda_output"] = time.time() - start_time
        return state

    def _emergency_loop(self) -> None:
        while self._running and not self._thread_stop.is_set():
            if self._emergency_until > 0 and time.monotonic() < self._emergency_until:
                try:
                    self._stream_emergency_blank_frame()
                except OSError:
                    pass
                sleep_seconds = 1.0 / max(1.0, self.config.target_fps)
            else:
                sleep_seconds = 0.05
            self._thread_stop.wait(timeout=sleep_seconds)

    @staticmethod
    def _blank_frame_for_fixture(fixture: FixtureConfig) -> ILDAFrame:
        return ILDAFrame(
            fixture_id=fixture.id,
            profile_name="ilda-blank",
            geometry_family="blank",
            color_mode="off",
            target_bias="mixed",
            point_count=2,
            repeat=True,
            points=[
                ILDAPoint(x=0, y=0, r=0, g=0, b=0, blanked=True),
                ILDAPoint(x=0, y=0, r=0, g=0, b=0, blanked=True),
            ],
        )

    def _build_blank_dac_frame(self) -> ILDAFrame:
        return self._merge_frames_for_dac(
            [self._blank_frame_for_fixture(fixture) for fixture in self.ilda_fixtures]
        )

    @staticmethod
    def _merge_frames_for_dac(frames: list[ILDAFrame]) -> ILDAFrame:
        merged_points: list[ILDAPoint] = []
        for frame in frames:
            points = frame["points"]
            if not points:
                continue
            if merged_points:
                separator = points[0].copy()
                separator["blanked"] = True
                separator["r"] = 0
                separator["g"] = 0
                separator["b"] = 0
                merged_points.append(separator)
            merged_points.extend(points)

        return ILDAFrame(
            fixture_id="ilda-composite",
            profile_name="ether_dream_composite",
            geometry_family="composite",
            color_mode="mixed",
            target_bias="mixed",
            point_count=len(merged_points),
            repeat=True,
            points=merged_points,
        )

    def _stream_frames(self, frame: ILDAFrame) -> None:
        if not frame["points"]:
            return
        point_rate = max(1, int(self.config.target_fps * frame["point_count"]))
        with self._transport_lock:
            try:
                self._ensure_ether_dream_client().ensure_streaming(frame, point_rate=point_rate)
                self._state_frames_sent += 1
            except OSError as exc:
                self._handle_ether_dream_error(exc)

    def _ensure_ether_dream_client(self) -> EtherDreamClient:
        if self._ether_dream is None:
            client = EtherDreamClient(self.config)
            client.connect()
            self._ether_dream = client
            if self._ether_dream_faulted:
                logger.info(
                    "Ether Dream transport recovered",
                    host=self.config.ether_dream_host,
                    port=self.config.ether_dream_port,
                )
            self._ether_dream_faulted = False
        return self._ether_dream

    def _handle_ether_dream_error(self, exc: OSError) -> None:
        client = self._ether_dream
        if client is not None:
            try:
                client.close()
            except OSError:
                pass
            self._ether_dream = None
        if not self._ether_dream_faulted:
            logger.warning(
                "Ether Dream transport faulted; will retry on next frame",
                host=self.config.ether_dream_host,
                port=self.config.ether_dream_port,
                error=str(exc),
            )
        self._ether_dream_faulted = True
