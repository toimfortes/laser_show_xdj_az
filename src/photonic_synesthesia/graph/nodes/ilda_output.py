"""ILDA frame generation node for hybrid laser fixtures."""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

from photonic_synesthesia.core.config import FixtureConfig, ILDAConfig, LaserSafetyConfig
from photonic_synesthesia.core.logging import get_logger
from photonic_synesthesia.core.state import ILDAFrame, ILDAPoint, MusicStructure, PhotonicState
from photonic_synesthesia.laser import build_laser_profiles
from photonic_synesthesia.laser.ether_dream import EtherDreamClient
from photonic_synesthesia.laser.ilda_file import encode_ild

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
) -> tuple[int, int, int]:
    if color_mode == "white_hits":
        peak = int(140 + 115 * max(color_drive, harshness))
        return peak, peak, peak
    if color_mode == "dual_cycle":
        red = int(90 + 165 * (0.5 + 0.5 * math.sin(phase)))
        blue = int(90 + 165 * (0.5 + 0.5 * math.sin(phase + math.pi)))
        green = int(30 + 100 * color_drive)
        return red, green, blue
    if color_mode == "morph":
        red = int(60 + 195 * (0.5 + 0.5 * math.sin(phase)))
        green = int(60 + 195 * (0.5 + 0.5 * math.sin(phase + 2.1)))
        blue = int(60 + 195 * (0.5 + 0.5 * math.sin(phase + 4.2)))
        return red, green, blue
    return 0, int(160 + 95 * color_drive), 255


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
        self._ether_dream: EtherDreamClient | None = None
        self._ether_dream_faulted = False

    def start(self) -> None:
        self._running = True
        if self.config.transport_type == "json" and self._export_path is not None:
            self._export_path.parent.mkdir(parents=True, exist_ok=True)
        if self.config.transport_type == "ild" and self._export_path is not None:
            self._export_path.parent.mkdir(parents=True, exist_ok=True)
        if self.config.transport_type == "ether_dream":
            self._ensure_ether_dream_client()

    def stop(self) -> None:
        if self._ether_dream is not None:
            self._ether_dream.close()
            self._ether_dream = None
        self._ether_dream_faulted = False
        self._running = False

    def __call__(self, state: PhotonicState) -> PhotonicState:
        start_time = time.time()
        if not self.config.enabled or not self.fixtures:
            state["ilda_frames"] = []
            state["processing_times"]["ilda_output"] = time.time() - start_time
            return state

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
            "ether_dream_host": self.config.ether_dream_host if self.config.transport_type == "ether_dream" else None,
            "ether_dream_faulted": self._ether_dream_faulted if self.config.transport_type == "ether_dream" else None,
        }

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
        if self._ether_dream is not None:
            try:
                self._ether_dream.close()
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

    def _frame_for_fixture(self, fixture: FixtureConfig, state: PhotonicState) -> ILDAFrame:
        profile = self.fixture_profiles[fixture.id]
        structure = state["current_structure"]
        beat_phase = state["beat_info"]["beat_phase"]
        bpm = state["fused_bpm"]
        timestamp = state["timestamp"]
        audio = state["audio_features"]
        director = state["director_state"]

        geometry_family = self._geometry_family(structure, director["laser_aggression"])
        color_mode = self._color_mode(director["color_drive"], audio["timbral_harshness"])
        target_bias = self._target_bias(
            director["melodic_smoothness"],
            director["laser_aggression"],
            structure,
        )
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
            harshness=audio["timbral_harshness"],
            color_drive=director["color_drive"],
            aggression=director["laser_aggression"],
            melodic_smoothness=director["melodic_smoothness"],
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
        harshness: float,
        color_drive: float,
        aggression: float,
        melodic_smoothness: float,
    ) -> list[ILDAPoint]:
        sweep_phase = timestamp * max(0.25, bpm / 60.0) * (0.5 + aggression * 1.8)
        amplitude_x = 0.35 + aggression * 0.45
        amplitude_y = min(
            self.safety.y_axis_max / 255.0,
            0.12 + melodic_smoothness * 0.28 + pitch_height * 0.18,
        )
        if geometry_family == "burst":
            amplitude_x += 0.08
            amplitude_y += 0.04
        elif geometry_family == "sky":
            amplitude_y += 0.12
        elif geometry_family == "rake":
            amplitude_x *= 0.8
            amplitude_y += 0.08

        y_offset = {
            "crowd": -0.2,
            "mid_air": 0.05,
            "ceiling": 0.28,
        }[target_bias]
        y_offset = min(y_offset, (self.safety.y_axis_max / 255.0) - amplitude_y)
        beat_boost = 1.0 + 0.22 * math.sin(beat_phase * math.pi * 2.0)
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
            else:
                x = math.sin(shape_phase * 0.7) * amplitude_x * 0.75
                y = y_offset + abs(math.sin(shape_phase * 0.9)) * amplitude_y

            color_phase = shape_phase + harmonic_change * 5.0
            r, g, b = _rgb_from_mode(color_mode, color_phase, color_drive, harshness)
            blanked = False
            if geometry_family == "burst" and aggression > 0.72:
                blanked = (index % 5) in {0, 1} and beat_phase < 0.22
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
            self._export_path.write_bytes(encode_ild(frames))
            return
        if self.config.transport_type == "ether_dream" and frames:
            try:
                point_rate = max(1, int(self.config.target_fps * max(frame["point_count"] for frame in frames)))
                self._ensure_ether_dream_client().ensure_streaming(frames[0], point_rate=point_rate)
            except OSError as exc:
                self._handle_ether_dream_error(exc)
