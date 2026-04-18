"""Runtime-facing control-plane state service and adapters."""

from __future__ import annotations

from threading import Lock
from typing import Any, cast

from photonic_synesthesia.core.state import ControlState, MusicStructure, PhotonicState
from photonic_synesthesia.platform.authority import ControlAuthorityService
from photonic_synesthesia.platform.clock import PlatformClock, SystemClock
from photonic_synesthesia.platform.commands import CommandReceipt, InMemoryCommandBus
from photonic_synesthesia.platform.contracts import (
    CommandType,
    DirectorSummary,
    ExecutionSnapshot,
    LeaseAcquireRequest,
    LeaseAcquireResponse,
    LiveHealth,
    OperatorCommand,
    PlatformEvent,
    PlatformEventType,
    SafetySummary,
    SemanticFrame,
)
from photonic_synesthesia.platform.events import InMemoryEventBus


class ControlPlaneStateService:
    """Owns control-plane state, command side effects, and runtime adaptation."""

    def __init__(
        self,
        clock: PlatformClock | None = None,
        commands: InMemoryCommandBus | None = None,
        events: InMemoryEventBus | None = None,
        authority: ControlAuthorityService | None = None,
    ) -> None:
        self.clock = clock or SystemClock()
        self.commands = commands or InMemoryCommandBus()
        self.events = events or InMemoryEventBus()
        self.authority = authority or ControlAuthorityService()

        self._lock = Lock()
        self._armed_live = False
        self._blackout_active = False
        self._global_intensity = 1.0
        self._global_speed = 1.0
        self._active_scene_id: str | None = None
        self._pending_scene_id: str | None = None
        self._scene_hold: str | None = None
        self._semantic_frame = SemanticFrame()
        self._director_summary = DirectorSummary()
        self._safety_summary = SafetySummary()
        self._diagnostics: dict[str, Any] = {
            "runtime_source": "control_plane_defaults",
            "runtime_frames_seen": 0,
        }

    def snapshot(self) -> ExecutionSnapshot:
        with self._lock:
            return ExecutionSnapshot(
                armed_live=self._armed_live,
                blackout_active=self._blackout_active,
                active_scene_id=self._active_scene_id,
                pending_scene_id=self._pending_scene_id,
                effective_global_intensity=self._global_intensity,
                effective_global_speed=self._global_speed,
                active_control_lease=self.authority.get_active_lease(),
                semantic_frame=self._semantic_frame.model_copy(deep=True),
                director_summary=self._director_summary.model_copy(deep=True),
                safety_summary=self._safety_summary.model_copy(deep=True),
                diagnostics={
                    **self._diagnostics,
                    "monotonic_ms": self.clock.monotonic_ms(),
                    "command_backlog": self.commands.backlog(),
                    "scene_hold": self._scene_hold,
                },
                recent_events=self.events.recent()[-10:],
            )

    def health(self, version: str, web_features: list[str] | None = None) -> LiveHealth:
        return LiveHealth(
            service="photonic-web",
            version=version,
            control_plane_online=True,
            active_control_lease=self.authority.get_active_lease(),
            command_backlog=self.commands.backlog(),
            recent_event_count=self.events.count(),
            web_features=web_features or [],
        )

    def publish_event(
        self,
        event_type: PlatformEventType,
        message: str,
        **payload: Any,
    ) -> PlatformEvent:
        event = PlatformEvent(
            event_type=event_type,
            message=message,
            payload=payload,
        )
        self.events.publish(event)
        return event

    def accept_command(self, command: OperatorCommand) -> CommandReceipt:
        self._apply_command_effects(command)
        receipt = self.commands.publish(command)
        self.publish_event(
            PlatformEventType.COMMAND_ACCEPTED,
            "Command accepted by control-plane service",
            command_id=command.command_id,
            command_type=command.command_type.value,
            target=command.target,
        )
        return receipt

    def acquire_control_lease(self, request: LeaseAcquireRequest) -> LeaseAcquireResponse:
        response = self.authority.acquire(request)
        event_type = (
            PlatformEventType.CONTROL_LEASE_ACQUIRED
            if response.granted
            else PlatformEventType.COMMAND_REJECTED
        )
        self.publish_event(
            event_type,
            response.message,
            issuer_id=request.issuer_id,
            session_id=request.session_id,
        )
        if response.granted:
            self.accept_command(
                OperatorCommand(
                    issuer_id=request.issuer_id,
                    session_id=request.session_id,
                    role=request.role,
                    command_type=CommandType.ACQUIRE_CONTROL_LEASE,
                )
            )
        return response

    def release_control_lease(self, session_id: str, force: bool = False) -> bool:
        released = self.authority.release(session_id, force=force)
        if released:
            self.publish_event(
                PlatformEventType.CONTROL_LEASE_RELEASED,
                "Control lease released",
                session_id=session_id,
                force=force,
            )
        return released

    def has_control(self, session_id: str) -> bool:
        return self.authority.has_control(session_id)

    def update_from_photonic_state(
        self,
        state: PhotonicState,
        source: str = "graph",
        node_stats: dict[str, dict[str, Any]] | None = None,
    ) -> ExecutionSnapshot:
        scene_state = state["scene_state"]
        beat_info = state["beat_info"]
        director = state["director_state"]
        safety = state["safety_state"]
        current_structure = state["current_structure"]

        structure_value = (
            current_structure.value
            if isinstance(current_structure, MusicStructure)
            else str(current_structure)
        )

        semantic_frame = SemanticFrame(
            bpm=float(state["fused_bpm"]),
            bpm_source=str(state["bpm_source"]),
            structure=structure_value,
            structure_confidence=float(state["structure_confidence"]),
            beat_phase=float(beat_info["beat_phase"]),
            beat_confidence=float(beat_info["confidence"]),
            downbeat=bool(beat_info["downbeat"]),
            drop_probability=float(state["drop_probability"]),
            harmonic_ratio=float(state["audio_features"]["harmonic_ratio"]),
            percussive_ratio=float(state["audio_features"]["percussive_ratio"]),
            tonal_stability=float(state["audio_features"]["tonal_stability"]),
            harmonic_change=float(state["audio_features"]["harmonic_change"]),
            harmonic_tension=float(state["audio_features"]["harmonic_tension"]),
            pitch_salience=float(state["audio_features"]["pitch_salience"]),
            pitch_height=float(state["audio_features"]["pitch_height"]),
            melodic_contour=float(state["audio_features"]["melodic_contour"]),
            melodic_stability=float(state["audio_features"]["melodic_stability"]),
            onset_density=float(state["audio_features"]["onset_density"]),
            timbral_harshness=float(state["audio_features"]["timbral_harshness"]),
        )
        director_summary = DirectorSummary(
            target_scene=str(director["target_scene"]),
            energy_level=float(director["energy_level"]),
            color_theme=str(director["color_theme"]),
            movement_style=str(director["movement_style"]),
            strobe_budget_hz=float(director["strobe_budget_hz"]),
            melodic_smoothness=float(director["melodic_smoothness"]),
            laser_aggression=float(director["laser_aggression"]),
            color_drive=float(director["color_drive"]),
            laser_motion_energy=float(director["laser_motion_energy"]),
            laser_color_energy=float(director["laser_color_energy"]),
            phrase_role=str(director["phrase_role"]),
            subphrase_role=str(director["subphrase_role"]),
            fill_pressure=float(director["fill_pressure"]),
            phrase_intensity=float(director["phrase_intensity"]),
            allow_scene_transition=bool(director["allow_scene_transition"]),
        )
        safety_summary = SafetySummary(
            ok=bool(safety["ok"]),
            error_state=cast(str | None, safety["error_state"]),
            laser_enabled=bool(safety["laser_enabled"]),
            strobe_enabled=bool(safety["strobe_enabled"]),
            emergency_stop=bool(safety["emergency_stop"]),
        )

        with self._lock:
            self._active_scene_id = cast(str | None, scene_state["current_scene"])
            self._pending_scene_id = cast(str | None, scene_state["pending_scene"])
            control_state = state["control_state"]
            self._armed_live = bool(control_state["armed_live"])
            self._blackout_active = bool(control_state["blackout_active"])
            self._global_intensity = float(control_state["global_intensity"])
            self._global_speed = float(control_state["global_speed"])
            self._scene_hold = cast(str | None, control_state["scene_hold"])
            self._semantic_frame = semantic_frame
            self._director_summary = director_summary
            self._safety_summary = safety_summary
            self._blackout_active = self._blackout_active or safety_summary.emergency_stop
            runtime_frames_seen = int(self._diagnostics.get("runtime_frames_seen", 0)) + 1
            node_stats = node_stats or {}
            ilda_stats = dict(node_stats.get("ilda_output", {}))
            if (
                "ether_dream_host" not in ilda_stats
                and "ilda_transport" in node_stats
                and isinstance(node_stats["ilda_transport"], dict)
            ):
                ilda_stats = {**ilda_stats, **dict(node_stats["ilda_transport"])}
            self._diagnostics = {
                "runtime_source": source,
                "runtime_frames_seen": runtime_frames_seen,
                "frame_number": int(state["frame_number"]),
                "sensor_status": dict(state["sensor_status"]),
                "processing_times": dict(state["processing_times"]),
                "dmx_universe_size": len(state["dmx_universe"]),
                "ilda_frame_count": len(state["ilda_frames"]),
                "ilda_geometry_families": [
                    str(frame["geometry_family"]) for frame in state["ilda_frames"]
                ],
                "ilda_fixture_ids": [str(frame["fixture_id"]) for frame in state["ilda_frames"]],
                "ilda_transport_type": ilda_stats.get("transport_type"),
                "ilda_transport_host": ilda_stats.get("ether_dream_host"),
                "ilda_transport_faulted": ilda_stats.get("ether_dream_faulted"),
            }

        self.publish_event(
            PlatformEventType.LIVE_STATE_PUBLISHED,
            "Runtime state ingested",
            source=source,
            frame_number=state["frame_number"],
        )
        return self.snapshot()

    def consume_control_snapshot_for_graph(self) -> ControlState:
        """Return the current control state and consume one-shot launch/command state."""
        commands = self.commands.drain()
        if commands:
            self._apply_command_batch_effects(commands)
        with self._lock:
            control_state: ControlState = {
                "armed_live": self._armed_live,
                "blackout_active": self._blackout_active,
                "global_intensity": self._global_intensity,
                "global_speed": self._global_speed,
                "scene_hold": self._scene_hold,
                "launched_scene": self._pending_scene_id,
            }
            self._pending_scene_id = None

        return control_state

    def _apply_command_batch_effects(self, commands: list[OperatorCommand]) -> None:
        with self._lock:
            armed_live = self._armed_live
            blackout_active = self._blackout_active
            global_intensity = self._global_intensity
            global_speed = self._global_speed
            scene_hold = self._scene_hold
            pending_scene_id = self._pending_scene_id

            should_blackout = False
            should_disarm = False
            should_clear_blackout = False

            for command in commands:
                if command.command_type == CommandType.ARM:
                    armed_live = True
                elif command.command_type == CommandType.DISARM:
                    armed_live = False
                    should_disarm = True
                    should_blackout = True
                elif command.command_type == CommandType.BLACKOUT:
                    should_blackout = True
                elif command.command_type == CommandType.CLEAR_BLACKOUT:
                    should_clear_blackout = True
                elif command.command_type == CommandType.SET_GLOBAL_INTENSITY:
                    global_intensity = max(
                        0.0,
                        min(
                            1.0,
                            float(command.payload.get("intensity", global_intensity)),
                        ),
                    )
                elif command.command_type == CommandType.SET_GLOBAL_SPEED:
                    global_speed = max(
                        0.0,
                        float(command.payload.get("speed", global_speed)),
                    )
                elif command.command_type == CommandType.LAUNCH_SCENE:
                    pending_scene_id = cast(str | None, command.payload.get("scene_id"))
                elif command.command_type == CommandType.HOLD_SCENE:
                    scene_hold = cast(str | None, command.payload.get("scene_id"))
                elif command.command_type == CommandType.RELEASE_SCENE_HOLD:
                    scene_hold = None

            if should_disarm:
                armed_live = False
                blackout_active = True
            else:
                if should_blackout:
                    blackout_active = True
                elif should_clear_blackout and self._armed_live and not should_blackout:
                    # Preserve legacy semantics: clear requests are ignored when system
                    # is disarmed at graph ingestion time.
                    blackout_active = False

            self._armed_live = armed_live
            self._blackout_active = blackout_active
            self._global_intensity = global_intensity
            self._global_speed = global_speed
            self._pending_scene_id = pending_scene_id
            self._scene_hold = scene_hold

    def _apply_command_effects(self, command: OperatorCommand) -> None:
        self._apply_command_batch_effects([command])
