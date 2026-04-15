"""Typed contracts for the scalable platform and control plane."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class OperatorRole(str, Enum):
    """Operator roles exposed by the control plane."""

    OBSERVER = "observer"
    OPERATOR = "operator"
    PROGRAMMER = "programmer"
    ADMIN = "admin"


class CommandType(str, Enum):
    """Command types entering the control plane."""

    ARM = "arm"
    DISARM = "disarm"
    BLACKOUT = "blackout"
    CLEAR_BLACKOUT = "clear_blackout"
    SET_GLOBAL_INTENSITY = "set_global_intensity"
    SET_GLOBAL_SPEED = "set_global_speed"
    SET_AUTO_MODE = "set_auto_mode"
    HOLD_SCENE = "hold_scene"
    RELEASE_SCENE_HOLD = "release_scene_hold"
    LAUNCH_SCENE = "launch_scene"
    SET_FIXTURE_GROUP_OVERRIDE = "set_fixture_group_override"
    CLEAR_FIXTURE_GROUP_OVERRIDE = "clear_fixture_group_override"
    SET_PALETTE_OVERRIDE = "set_palette_override"
    SET_TRANSPORT_STATE = "set_transport_state"
    ACQUIRE_CONTROL_LEASE = "acquire_control_lease"
    RELEASE_CONTROL_LEASE = "release_control_lease"


class PlatformEventType(str, Enum):
    """Event types emitted by the platform."""

    COMMAND_ACCEPTED = "command_accepted"
    COMMAND_REJECTED = "command_rejected"
    CONTROL_LEASE_ACQUIRED = "control_lease_acquired"
    CONTROL_LEASE_RELEASED = "control_lease_released"
    SAFETY_TRIP = "safety_trip"
    SAFETY_CLEARED = "safety_cleared"
    LIVE_STATE_PUBLISHED = "live_state_published"
    REPLAY_STARTED = "replay_started"
    REPLAY_STOPPED = "replay_stopped"


class OperatorCommand(BaseModel):
    """Canonical control-plane command."""

    command_id: str = Field(default_factory=lambda: _id("cmd"))
    issued_at: datetime = Field(default_factory=_utc_now)
    issuer_id: str
    session_id: str
    role: OperatorRole
    command_type: CommandType
    target: str = "system"
    payload: dict[str, Any] = Field(default_factory=dict)


class PlatformEvent(BaseModel):
    """Canonical platform event."""

    event_id: str = Field(default_factory=lambda: _id("evt"))
    emitted_at: datetime = Field(default_factory=_utc_now)
    event_type: PlatformEventType
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ControlLease(BaseModel):
    """Active control lease state."""

    lease_id: str = Field(default_factory=lambda: _id("lease"))
    issuer_id: str
    session_id: str
    role: OperatorRole
    acquired_at: datetime = Field(default_factory=_utc_now)
    expires_at: datetime


class LeaseAcquireRequest(BaseModel):
    """Request payload for acquiring the live control lease."""

    issuer_id: str
    session_id: str
    role: OperatorRole = OperatorRole.OPERATOR
    ttl_seconds: int = Field(default=300, ge=30, le=3600)
    force: bool = False


class LeaseAcquireResponse(BaseModel):
    """Response payload for acquiring or inspecting a lease."""

    granted: bool
    lease: ControlLease | None = None
    message: str


class LiveHealth(BaseModel):
    """High-level health summary exposed by the website."""

    service: str
    version: str
    control_plane_online: bool
    active_control_lease: ControlLease | None = None
    command_backlog: int = 0
    recent_event_count: int = 0
    web_features: list[str] = Field(default_factory=list)


class SemanticFrame(BaseModel):
    """Semantic summary for live inspection and replay."""

    bpm: float = 0.0
    bpm_source: str = "unknown"
    structure: str = "unknown"
    structure_confidence: float = 0.0
    beat_phase: float = 0.0
    beat_confidence: float = 0.0
    downbeat: bool = False
    drop_probability: float = 0.0


class DirectorSummary(BaseModel):
    """Director-facing runtime summary."""

    target_scene: str = "idle"
    energy_level: float = 0.0
    color_theme: str = "neutral"
    movement_style: str = "steady"
    strobe_budget_hz: float = 0.0
    allow_scene_transition: bool = True


class SafetySummary(BaseModel):
    """Safety summary for website and replay inspection."""

    ok: bool = True
    error_state: str | None = None
    laser_enabled: bool = True
    strobe_enabled: bool = True
    emergency_stop: bool = False


class ExecutionSnapshot(BaseModel):
    """Lightweight live snapshot contract for the web control plane."""

    snapshot_id: str = Field(default_factory=lambda: _id("snap"))
    captured_at: datetime = Field(default_factory=_utc_now)
    armed_live: bool = False
    blackout_active: bool = False
    active_scene_id: str | None = None
    pending_scene_id: str | None = None
    effective_global_intensity: float = Field(default=1.0, ge=0.0, le=1.0)
    effective_global_speed: float = Field(default=1.0, ge=0.0)
    active_control_lease: ControlLease | None = None
    semantic_frame: SemanticFrame = Field(default_factory=SemanticFrame)
    director_summary: DirectorSummary = Field(default_factory=DirectorSummary)
    safety_summary: SafetySummary = Field(default_factory=SafetySummary)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    recent_events: list[PlatformEvent] = Field(default_factory=list)
