"""FastAPI-based control plane for the optional web interface."""

import asyncio
import copy
import functools
import math
import os
import random
import socket
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

# pydantic is a core dependency, so BaseModel is always importable. Only
# the fastapi/uvicorn stack is optional, so that import still goes
# through _import_web_stack() below.
from pydantic import BaseModel

from photonic_synesthesia import __version__
from photonic_synesthesia.core.logging import get_logger
from photonic_synesthesia.platform import (
    CommandType,
    ControlPlaneStateService,
    LeaseAcquireRequest,
    OperatorCommand,
    OperatorRole,
    PlatformEventType,
    PlaybackContext,
    get_shared_control_plane_service,
    get_shared_playback_context,
)
from photonic_synesthesia.platform import rig_storage

logger = get_logger(__name__)

# Cycle-3-rev-2 R6 (Codex + Gemini): fields that MUST NOT be logged
# verbatim. `session_id` is the credential `require_control()` checks
# (logging it leaks a replayable control token); `issuer_id` is the
# operator's identifier (PII for audit-trail compliance). Other secrets
# go here as they're added.
#
# `cue_recipe` and `laser_program` are also redacted because they can be
# multi-KB nested dicts that drown out the actual operation context.
_LOG_REDACTED_FIELDS = frozenset({
    "session_id",
    "issuer_id",
})
_LOG_TRUNCATED_FIELDS = frozenset({
    "cue_recipe",
    "laser_program",
    "show_sections",
    "timeline_flags",
    "metadata",
})


def _redact_log_payload(data: Any) -> Any:
    """Return a copy of `data` with secret fields hashed and large
    payloads replaced with their type+size summary.

    `session_id` and `issuer_id` are turned into `"<redacted:8-char-hash>"`
    so the log retains correlatability across requests in the same
    session without leaking the raw credential.
    """
    if not isinstance(data, dict):
        return data
    out: dict[str, Any] = {}
    for key, value in data.items():
        if key in _LOG_REDACTED_FIELDS and value is not None:
            try:
                import hashlib
                digest = hashlib.sha1(str(value).encode("utf-8")).hexdigest()[:8]
                out[key] = f"<redacted:{digest}>"
            except Exception:
                out[key] = "<redacted>"
        elif key in _LOG_TRUNCATED_FIELDS and value is not None:
            type_name = type(value).__name__
            size_hint = len(value) if hasattr(value, "__len__") else "?"
            out[key] = f"<{type_name}:len={size_hint}>"
        elif isinstance(value, dict):
            out[key] = _redact_log_payload(value)
        else:
            out[key] = value
    return out


def log_endpoint(op: str):
    """Decorator: log endpoint entry, exit-with-duration, and exceptions.

    Cycle-3 destructive review D1 fix: previously 0/36 endpoints had any
    logging; debugging the catastrophic crash was impossible because no
    application telemetry survived the failure. This decorator emits:
        - INFO at entry with the operation name + redacted request fields
        - INFO at exit with `op` + `duration_ms`
        - ERROR with full exception context if the handler raises

    Cycle-3-rev-2 R6 fix: request payloads run through
    `_redact_log_payload` to hash credentials (`session_id`, `issuer_id`)
    and truncate large nested fields (`cue_recipe`, `laser_program`).

    Uses the in-repo `get_logger` (structlog-style kwargs, falls back to
    stdlib logging when structlog isn't installed).
    """
    def decorator(handler):
        @functools.wraps(handler)
        async def wrapper(*args, **kwargs):
            start = time.perf_counter()
            # Cycle-4 Review B LOW-1: capture BOTH the request body (first
            # BaseModel arg) AND path/query params (remaining kwargs) so
            # the log line shows everything needed to replay the request.
            # Pre-fix only captured the first BaseModel arg, so a PATCH
            # like `/api/mock/fixtures/{fixture_id}` with body `{changes: {...}}`
            # logged `changes` but dropped `fixture_id` — debugging which
            # fixture was patched required cross-referencing timestamps.
            req_summary: dict[str, Any] | str | None = None
            params_summary: dict[str, Any] = {}
            for key, value in kwargs.items():
                if isinstance(value, BaseModel):
                    try:
                        raw = value.model_dump(exclude_none=True)
                        req_summary = _redact_log_payload(raw)
                    except Exception as exc:
                        req_summary = f"<serialization_failed:{type(exc).__name__}>"
                elif isinstance(value, (str, int, float, bool, type(None))):
                    # Path + query params: log primitive values.
                    params_summary[key] = value
            # Redact the params dict too (covers `session_id` that FastAPI
            # may route via path/query in some cases + keeps the log shape
            # consistent with body-field redaction).
            params_summary = _redact_log_payload(params_summary) if params_summary else {}
            logger.info(
                "endpoint_request",
                op=op,
                request=req_summary,
                params=params_summary or None,
            )
            try:
                result = await handler(*args, **kwargs)
            except Exception as exc:
                duration_ms = (time.perf_counter() - start) * 1000
                logger.exception(
                    "endpoint_error", op=op, duration_ms=round(duration_ms, 2),
                    error_type=type(exc).__name__, error=str(exc)[:200],
                ) if hasattr(logger, "exception") else logger.error(
                    "endpoint_error", op=op, duration_ms=round(duration_ms, 2),
                    error_type=type(exc).__name__, error=str(exc)[:200],
                )
                raise
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info("endpoint_response", op=op, duration_ms=round(duration_ms, 2))
            return result
        return wrapper
    return decorator

MOCK_FIXTURE_TEMPLATES: list[dict[str, Any]] = [
    {
        "slug": "laser",
        "label": "Laser Scanner",
        "type": "laser",
        "description": "Multi-beam fan with wide scan spread and fast rhythmic motion.",
        "defaults": {
            "color": "#12d8ff",
            "intensity": 0.9,
            "x": 0.18,
            "y": 0.16,
            "spread": 0.30,
            "beam_count": 5,
            "swing": 0.40,
            "universe": 1,
            "address": 1,
        },
    },
    {
        "slug": "moving_head",
        "label": "Moving Head",
        "type": "moving_head",
        "description": "Pan/tilt spot with beam cone, sweep range, and target motion.",
        "defaults": {
            "color": "#ff7a18",
            "intensity": 0.8,
            "x": 0.42,
            "y": 0.12,
            "pan": 0.0,
            "tilt": 0.55,
            "pan_range": 0.55,
            "tilt_range": 0.35,
            "beam_width": 0.10,
            "universe": 1,
            "address": 30,
        },
    },
    {
        "slug": "wash",
        "label": "Wash Fixture",
        "type": "wash",
        "description": "Soft color field for stage coverage and scene mood.",
        "defaults": {
            "color": "#ff4d6d",
            "intensity": 0.65,
            "x": 0.68,
            "y": 0.20,
            "radius": 0.22,
            "universe": 1,
            "address": 60,
        },
    },
    {
        "slug": "led_bar",
        "label": "LED Bar",
        "type": "led_bar",
        "description": "Pixel strip style bar for chases, accents, and audience wash.",
        "defaults": {
            "color": "#7cf29c",
            "intensity": 0.75,
            "x": 0.84,
            "y": 0.18,
            "pixel_count": 6,
            "width": 0.18,
            "universe": 1,
            "address": 90,
        },
    },
]

MOCK_SCENE_TEMPLATES: list[dict[str, Any]] = [
    {
        "scene_id": "intro_ambient",
        "label": "Intro Ambient",
        "palette": ["#12d8ff", "#ffc857", "#ff7a18"],
        "speed_multiplier": 0.55,
        "pulse": 0.35,
        "strobe": 0.0,
    },
    {
        "scene_id": "break_sweep",
        "label": "Break Sweep",
        "palette": ["#0ea5e9", "#f97316", "#fb7185"],
        "speed_multiplier": 0.9,
        "pulse": 0.5,
        "strobe": 0.05,
    },
    {
        "scene_id": "drop_intense",
        "label": "Drop Intense",
        "palette": ["#f94144", "#f8961e", "#90be6d"],
        "speed_multiplier": 1.4,
        "pulse": 0.85,
        "strobe": 0.18,
    },
]

MOCK_DEFAULT_RIG: list[dict[str, Any]] = [
    {"template": "laser", "label": "Laser A"},
    {"template": "moving_head", "label": "Mover A"},
    {"template": "moving_head", "label": "Mover B"},
    {"template": "wash", "label": "Wash A"},
    {"template": "led_bar", "label": "Bar A"},
]

_FIXTURE_TEMPLATE_INDEX = {item["slug"]: item for item in MOCK_FIXTURE_TEMPLATES}
_SCENE_TEMPLATE_INDEX = {item["scene_id"]: item for item in MOCK_SCENE_TEMPLATES}


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _normalize_float(value: Any, lower: float, upper: float) -> float:
    return _clamp(float(value), lower, upper)


def _normalize_int(value: Any, lower: int, upper: int) -> int:
    return max(lower, min(upper, int(value)))


def _normalize_color(value: Any) -> str:
    text = str(value).strip()
    if not text.startswith("#"):
        text = f"#{text}"
    if len(text) == 4:
        text = "#" + "".join(char * 2 for char in text[1:])
    if len(text) != 7:
        return "#ffffff"
    try:
        int(text[1:], 16)
    except ValueError:
        return "#ffffff"
    return text.lower()


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    normalized = _normalize_color(hex_color)
    value = int(normalized[1:], 16)
    return ((value >> 16) & 255, (value >> 8) & 255, value & 255)


def _build_mock_fixture(
    template_slug: str,
    existing_fixtures: list[dict[str, Any]],
    *,
    label_override: str | None = None,
) -> dict[str, Any]:
    template = _FIXTURE_TEMPLATE_INDEX.get(template_slug)
    if template is None:
        raise KeyError(template_slug)

    same_type_count = sum(1 for fixture in existing_fixtures if fixture["type"] == template["type"])
    defaults = copy.deepcopy(template["defaults"])
    defaults["x"] = _clamp(float(defaults["x"]) + same_type_count * 0.07, 0.08, 0.92)
    defaults["address"] = int(defaults["address"]) + same_type_count * 20
    # Cycle-1 panel resolution: every freshly-built fixture gets a default
    # `profile` (per `DEFAULT_PROFILE_BY_TYPE`) and `enabled=True` so the
    # rig-storage save path's type-profile invariant doesn't reject the
    # default rig (closes Kilo CRITICAL#3 + the snapshot UX).
    from photonic_synesthesia.platform.rig_storage import DEFAULT_PROFILE_BY_TYPE
    profile_default = DEFAULT_PROFILE_BY_TYPE.get(template["type"])
    return {
        "id": f"{template_slug}-{uuid.uuid4().hex[:8]}",
        "templateSlug": template["slug"],
        "type": template["type"],
        "label": label_override or f"{template['label']} {same_type_count + 1}",
        **defaults,
        "profile": profile_default,
        "enabled": True,
        "phaseOffset": random.random() * math.pi * 2.0,
    }


def _scene_mix(scene: dict[str, Any], time_seconds: float) -> float:
    return 0.55 + math.sin(time_seconds * float(scene["speed_multiplier"]) * 2.0) * float(
        scene["pulse"]
    ) * 0.35


def _palette_pick(palette: list[str], phase: float, offset: float) -> str:
    """Choose a hex color from a scene palette that cycles with phase."""
    if not palette:
        return "#ffffff"
    swept = (math.sin(phase * 0.45 + offset) + 1.0) * 0.5
    index = int(round(swept * (len(palette) - 1))) % len(palette)
    return palette[index]


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return f"#{max(0, min(255, rgb[0])):02x}{max(0, min(255, rgb[1])):02x}{max(0, min(255, rgb[2])):02x}"


def _director_color_snapshot() -> tuple[str, float, str, float, str] | None:
    """Return (color_theme, color_drive, structure, strobe_budget_hz, subphrase_role)
    from the live graph's director, or None when no graph is running.

    The web panel runs in the same process as the graph when
    `photonic run-file --web` (or `photonic run --web`) is used, so the
    shared ControlPlaneStateService and its DirectorSummary are reachable
    from here. Falls back to None in pure-mock environments.
    """
    try:
        from photonic_synesthesia.platform import get_shared_control_plane_service
    except Exception:  # pragma: no cover - platform always importable in prod
        return None
    try:
        service = get_shared_control_plane_service(create=False)
    except Exception:
        return None
    if service is None:
        return None
    try:
        snap = service.snapshot()
    except Exception:
        return None
    director = snap.director_summary
    semantic = snap.semantic_frame
    color_theme = getattr(director, "color_theme", "") or ""
    color_drive = float(getattr(director, "color_drive", 0.5) or 0.5)
    structure = getattr(semantic, "structure", "") or ""
    strobe_budget = float(getattr(director, "strobe_budget_hz", 0.0) or 0.0)
    subphrase_role = getattr(director, "subphrase_role", "") or ""
    return color_theme, color_drive, structure, strobe_budget, subphrase_role


def _mode_for_structure(structure: str) -> str:
    """Match fixture_control's color_mode policy for visual parity."""
    if structure in ("drop", "buildup"):
        return "dual_cycle"
    if structure == "breakdown":
        return "morph"
    return "static"


def _fixture_output(
    fixture: dict[str, Any],
    scene: dict[str, Any],
    *,
    time_seconds: float,
    master_intensity: float,
    master_speed: float,
    blackout: bool,
) -> dict[str, Any]:
    mix = _scene_mix(scene, time_seconds)
    phase = time_seconds * master_speed * float(scene["speed_multiplier"]) + float(
        fixture["phaseOffset"]
    )
    base_intensity = float(fixture["intensity"]) * master_intensity * mix
    intensity = 0.0 if blackout else _clamp(base_intensity, 0.0, 1.0)

    # Prefer live director state from the running graph so the preview
    # matches whatever real fixtures would render for this track. This
    # keeps the mock rig usable for show-planning decisions: the UI
    # shows the actual palette (poison, cyan_magenta, amber_cyan, etc.)
    # the director is picking per phrase.
    director_snapshot = _director_color_snapshot()
    if director_snapshot is not None:
        from photonic_synesthesia.director.palettes import render_rgb, resolve_palette

        color_theme, color_drive, structure, _strobe_budget, _subphrase_role = director_snapshot
        palette = resolve_palette(color_theme)
        render_mode = _mode_for_structure(structure)
        rgb = render_rgb(
            palette,
            render_mode,
            phase=phase,
            beat_hit=False,
            color_drive=color_drive,
        )
        color = _rgb_to_hex(rgb)
    else:
        # Fallback: sweep the scene's own palette (pure-mock mode, no
        # graph attached). Keeps the preview animated even when there's
        # no music source.
        scene_palette = list(scene.get("palette") or [])
        if scene_palette:
            color = _palette_pick(scene_palette, phase, float(fixture["phaseOffset"]))
        else:
            color = _normalize_color(fixture["color"])
    red, green, blue = _hex_to_rgb(color)

    if fixture["type"] == "laser":
        return {
            "type": "laser",
            "color": color,
            "intensity": intensity,
            "channels": [
                ("Dim", round(intensity * 255)),
                ("Color", round(green)),
                ("Pattern", 160 + round((math.sin(phase) + 1.0) * 20)),
                ("Scan", round((0.2 + float(fixture["swing"]) * 0.8) * 255)),
            ],
        }

    if fixture["type"] == "moving_head":
        return {
            "type": "moving_head",
            "color": color,
            "intensity": intensity,
            "channels": [
                ("Dim", round(intensity * 255)),
                ("Pan", round(((math.sin(phase) * 0.5) + 0.5) * 255)),
                ("Tilt", round(((math.cos(phase * 0.8) * 0.5) + 0.5) * 255)),
                ("Color", round(red)),
            ],
        }

    if fixture["type"] == "wash":
        return {
            "type": "wash",
            "color": color,
            "intensity": intensity,
            "channels": [
                ("Dim", round(intensity * 255)),
                ("Red", red),
                ("Green", green),
                ("Blue", blue),
            ],
        }

    return {
        "type": "led_bar",
        "color": color,
        "intensity": intensity,
        "channels": [
            ("Dim", round(intensity * 255)),
            ("Pixels", _normalize_int(fixture["pixel_count"], 2, 16)),
            ("Chase", round(((math.sin(phase * 1.6) + 1.0) * 0.5) * 255)),
            ("Color", round(blue)),
        ],
    }


class MockRigStore:
    """Server-owned mock rig state for the browser preview."""

    def __init__(self, *, initial_fixtures: list[dict[str, Any]] | None = None) -> None:
        """Construct a MockRigStore.

        Cycle-1 panel rig-storage Phase A: if `initial_fixtures` is
        supplied (e.g. from an active rig hydration in `create_app`),
        skip `_seed_default_rig` and use the provided list directly.
        Falls back to defaults on validation failure (caller logs the
        warning) so the UI is never empty.
        """
        self._lock = threading.Lock()
        self._fixtures: list[dict[str, Any]] = []
        self._scene_id = MOCK_SCENE_TEMPLATES[0]["scene_id"]
        self._master_intensity = 0.82
        self._master_speed = 1.0
        self._blackout = False
        if initial_fixtures is not None:
            try:
                self._validate_fixture_list(initial_fixtures)
                self._fixtures = copy.deepcopy(initial_fixtures)
                return
            except ValueError as exc:
                logger.warning(
                    "mock_rig_initial_fixtures_invalid",
                    error=str(exc),
                    fallback="default_rig",
                )
        self._seed_default_rig()

    def _seed_default_rig(self) -> None:
        self._fixtures = []
        for entry in MOCK_DEFAULT_RIG:
            self._fixtures.append(
                _build_mock_fixture(entry["template"], self._fixtures, label_override=entry["label"])
            )

    @staticmethod
    def _validate_fixture_list(fixtures: list[dict[str, Any]]) -> None:
        """Cycle-1 panel Claude M5: validate ID uniqueness + basic
        structural invariants BEFORE swap so partial bad data cannot
        replace a good in-memory state."""
        if not isinstance(fixtures, list):
            raise ValueError("fixtures payload must be a list")
        seen: set[str] = set()
        for fixture in fixtures:
            if not isinstance(fixture, dict):
                raise ValueError("each fixture must be a dict")
            fid = fixture.get("id")
            if not isinstance(fid, str) or not fid:
                raise ValueError(f"fixture must have non-empty string id; got {fid!r}")
            if fid in seen:
                raise ValueError(f"duplicate fixture id {fid!r}")
            seen.add(fid)
            if "type" not in fixture:
                raise ValueError(f"fixture {fid!r} missing `type`")

    def replace_all(self, fixtures: list[dict[str, Any]]) -> None:
        """Atomically replace the in-memory fixture list under `_lock`.

        Cycle-1 panel Claude M5: validates BEFORE swap; on any failure
        the prior state is preserved (no partial replace). After swap,
        the UI MUST clear `selectedFixtureId` (the load endpoint hands
        that out in its response payload).
        """
        self._validate_fixture_list(fixtures)
        deep = copy.deepcopy(fixtures)
        with self._lock:
            self._fixtures = deep

    def dump(self) -> list[dict[str, Any]]:
        """Return a deep-copy of the current fixtures list (cycle-1
        panel A7 — caller may mutate without touching internal state)."""
        with self._lock:
            return copy.deepcopy(self._fixtures)

    def catalog(self) -> dict[str, Any]:
        return {
            "fixture_templates": copy.deepcopy(MOCK_FIXTURE_TEMPLATES),
            "scene_templates": copy.deepcopy(MOCK_SCENE_TEMPLATES),
            "default_rig": copy.deepcopy(MOCK_DEFAULT_RIG),
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "fixtures": copy.deepcopy(self._fixtures),
                "scene_id": self._scene_id,
                "master_intensity": self._master_intensity,
                "master_speed": self._master_speed,
                "blackout": self._blackout,
            }

    def _fixture_by_id(self, fixture_id: str) -> dict[str, Any] | None:
        for fixture in self._fixtures:
            if fixture["id"] == fixture_id:
                return fixture
        return None

    def create_fixture(self, template_slug: str, label: str | None = None) -> dict[str, Any]:
        with self._lock:
            fixture = _build_mock_fixture(template_slug, self._fixtures, label_override=label)
            self._fixtures.append(fixture)
            return copy.deepcopy(fixture)

    def duplicate_fixture(self, fixture_id: str) -> dict[str, Any] | None:
        with self._lock:
            fixture = self._fixture_by_id(fixture_id)
            if fixture is None:
                return None
            clone = copy.deepcopy(fixture)
            clone["id"] = f"{fixture['templateSlug']}-{uuid.uuid4().hex[:8]}"
            clone["label"] = f"{fixture['label']} Copy"
            clone["x"] = _clamp(float(fixture["x"]) + 0.05, 0.05, 0.95)
            clone["address"] = _normalize_int(int(fixture["address"]) + 10, 1, 512)
            self._fixtures.append(clone)
            return copy.deepcopy(clone)

    def delete_fixture(self, fixture_id: str) -> bool:
        with self._lock:
            original_len = len(self._fixtures)
            self._fixtures = [fixture for fixture in self._fixtures if fixture["id"] != fixture_id]
            return len(self._fixtures) != original_len

    def update_fixture(self, fixture_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            fixture = self._fixture_by_id(fixture_id)
            if fixture is None:
                return None

            for key, value in changes.items():
                if key == "label":
                    fixture["label"] = str(value).strip()[:80] or fixture["label"]
                elif key == "color":
                    fixture["color"] = _normalize_color(value)
                elif key == "intensity":
                    fixture["intensity"] = _normalize_float(value, 0.0, 1.0)
                elif key == "x":
                    fixture["x"] = _normalize_float(value, 0.05, 0.95)
                elif key == "y":
                    fixture["y"] = _normalize_float(value, 0.05, 0.60)
                elif key == "universe":
                    fixture["universe"] = _normalize_int(value, 1, 32)
                elif key == "address":
                    fixture["address"] = _normalize_int(value, 1, 512)
                elif key == "spread" and fixture["type"] == "laser":
                    fixture["spread"] = _normalize_float(value, 0.05, 0.55)
                elif key == "beam_count" and fixture["type"] == "laser":
                    fixture["beam_count"] = _normalize_int(value, 1, 9)
                elif key == "swing" and fixture["type"] == "laser":
                    fixture["swing"] = _normalize_float(value, 0.0, 1.0)
                elif key == "beam_width" and fixture["type"] == "moving_head":
                    fixture["beam_width"] = _normalize_float(value, 0.04, 0.25)
                elif key == "pan" and fixture["type"] == "moving_head":
                    fixture["pan"] = _normalize_float(value, -1.0, 1.0)
                elif key == "tilt" and fixture["type"] == "moving_head":
                    fixture["tilt"] = _normalize_float(value, 0.0, 1.0)
                elif key == "pan_range" and fixture["type"] == "moving_head":
                    fixture["pan_range"] = _normalize_float(value, 0.0, 1.0)
                elif key == "tilt_range" and fixture["type"] == "moving_head":
                    fixture["tilt_range"] = _normalize_float(value, 0.0, 1.0)
                elif key == "radius" and fixture["type"] == "wash":
                    fixture["radius"] = _normalize_float(value, 0.08, 0.40)
                elif key == "width" and fixture["type"] == "led_bar":
                    fixture["width"] = _normalize_float(value, 0.08, 0.35)
                elif key == "pixel_count" and fixture["type"] == "led_bar":
                    fixture["pixel_count"] = _normalize_int(value, 2, 16)
                # Cycle-1 panel Kilo CRITICAL#3 + Codex H#3: profile and
                # enabled MUST be persistable via PATCH so the inspector's
                # new fields actually save. Previously, the whitelist
                # silently dropped these keys, making PATCH a no-op.
                elif key == "profile":
                    if value is None:
                        fixture["profile"] = None
                    else:
                        fixture["profile"] = str(value).strip() or None
                elif key == "enabled":
                    fixture["enabled"] = bool(value)

            return copy.deepcopy(fixture)

    def update_scene(self, scene_id: str) -> bool:
        if scene_id not in _SCENE_TEMPLATE_INDEX:
            return False
        with self._lock:
            self._scene_id = scene_id
        return True

    def update_masters(
        self,
        *,
        master_intensity: float | None = None,
        master_speed: float | None = None,
        blackout: bool | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if master_intensity is not None:
                self._master_intensity = _normalize_float(master_intensity, 0.0, 1.0)
            if master_speed is not None:
                self._master_speed = _normalize_float(master_speed, 0.2, 2.2)
            if blackout is not None:
                self._blackout = bool(blackout)
        return self.snapshot()

    def universe_snapshot(self, *, at_time: float | None = None) -> dict[str, Any]:
        state = self.snapshot()
        scene = _SCENE_TEMPLATE_INDEX[state["scene_id"]]
        generated_at = at_time if at_time is not None else time.time()
        universes: dict[int, dict[str, Any]] = {}

        for fixture in state["fixtures"]:
            output = _fixture_output(
                fixture,
                scene,
                time_seconds=generated_at,
                master_intensity=float(state["master_intensity"]),
                master_speed=float(state["master_speed"]),
                blackout=bool(state["blackout"]),
            )
            universe_id = int(fixture["universe"])
            universe = universes.setdefault(
                universe_id,
                {
                    "universe": universe_id,
                    "active_channel_count": 0,
                    "fixtures": [],
                    "channels": [],
                },
            )

            fixture_channels: list[dict[str, Any]] = []
            start_address = int(fixture["address"])
            for offset, (label, value) in enumerate(output["channels"]):
                channel = start_address + offset
                if channel > 512:
                    continue
                record = {
                    "channel": channel,
                    "offset": offset + 1,
                    "label": label,
                    "value": _normalize_int(value, 0, 255),
                }
                fixture_channels.append(record)
                universe["channels"].append(
                    {
                        "channel": channel,
                        "label": label,
                        "value": record["value"],
                        "fixture_id": fixture["id"],
                        "fixture_label": fixture["label"],
                    }
                )

            universe["fixtures"].append(
                {
                    "fixture_id": fixture["id"],
                    "fixture_label": fixture["label"],
                    "type": fixture["type"],
                    "address": fixture["address"],
                    "intensity": output["intensity"],
                    "channels": fixture_channels,
                }
            )

        ordered_universes = []
        for universe in sorted(universes.values(), key=lambda item: item["universe"]):
            universe["channels"].sort(key=lambda item: int(item["channel"]))
            universe["active_channel_count"] = len(universe["channels"])
            ordered_universes.append(universe)

        return {
            "generated_at": generated_at,
            "scene_id": state["scene_id"],
            "master_intensity": state["master_intensity"],
            "master_speed": state["master_speed"],
            "blackout": state["blackout"],
            "fixture_count": len(state["fixtures"]),
            "universes": ordered_universes,
        }


def _import_web_stack() -> tuple[Any, Any, Any, Any, Any, Any, Any]:
    try:
        from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
        from fastapi.responses import FileResponse, HTMLResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:  # pragma: no cover - exercised only in minimal envs
        raise RuntimeError(
            "The web control plane requires optional dependencies. "
            "Install with: pip install -e '.[web]'"
        ) from exc
    return (
        FastAPI,
        HTTPException,
        WebSocket,
        WebSocketDisconnect,
        HTMLResponse,
        FileResponse,
        StaticFiles,
    )


def _render_control_plane_html() -> str:
    return """
    <!DOCTYPE html>
    <html lang="en">
        <head>
            <meta charset="utf-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1" />
            <title>Photonic Synesthesia Control Plane</title>
            <link rel="stylesheet" href="/static/mock_control_plane.css" />
        </head>
        <body>
            <div id="app">
                <header class="hero">
                    <div class="hero-copy">
                        <p class="eyebrow">Photonic Synesthesia</p>
                        <h1>Control Plane</h1>
                        <p class="lede">Mock rig preview — add fixtures and watch them respond to live runtime.</p>
                    </div>
                    <div class="hero-metrics">
                        <div class="metric-card">
                            <span>WS</span>
                            <strong id="ws-status">connecting</strong>
                        </div>
                        <div class="metric-card">
                            <span>Scene</span>
                            <strong id="runtime-scene">idle</strong>
                        </div>
                        <div class="metric-card">
                            <span>Fixtures</span>
                            <strong id="fixture-count">0</strong>
                        </div>
                    </div>
                </header>

                <main class="layout">
                    <section class="panel stack" aria-label="Show controls">
                        <div class="panel-header">
                            <h2>Show Controls</h2>
                        </div>

                        <div class="stack compact">
                            <label class="range-field">
                                <span>Master Intensity</span>
                                <input id="master-intensity" type="range" min="0" max="1" step="0.01" value="0.82" />
                                <strong id="master-intensity-value">82%</strong>
                            </label>
                            <label class="range-field">
                                <span>Master Speed</span>
                                <input id="master-speed" type="range" min="0.2" max="2.2" step="0.01" value="1.00" />
                                <strong id="master-speed-value">1.00x</strong>
                            </label>
                            <button id="blackout-toggle" class="panic">Blackout Off</button>
                        </div>

                        <details open>
                            <summary><div class="subhead"><h3>Rig</h3></div></summary>
                            <div class="details-body">
                                <div id="fixture-list" class="fixture-list"></div>
                            </div>
                        </details>

                        <details>
                            <summary><div class="subhead"><h3>Scene Bank</h3></div></summary>
                            <div class="details-body">
                                <div id="scene-bank" class="scene-bank"></div>
                            </div>
                        </details>

                        <details>
                            <summary><div class="subhead"><h3>Fixture Library</h3></div></summary>
                            <div class="details-body">
                                <div id="fixture-library" class="fixture-library"></div>
                            </div>
                        </details>

                        <details open>
                            <summary><div class="subhead"><h3>Saved Rigs</h3></div></summary>
                            <div class="details-body">
                                <div id="rig-controls" class="rig-controls">
                                    Loading saved rigs…
                                </div>
                            </div>
                        </details>
                    </section>

                    <section class="panel preview-panel" aria-label="Stage preview">
                        <div class="panel-header wide">
                            <div>
                                <h2>Stage Preview</h2>
                                <p>Browser-only renderer with laser fans, beam cones, washes, and LED strip output.</p>
                            </div>
                            <div class="legend">
                                <span><i class="legend-chip laser"></i> Laser</span>
                                <span><i class="legend-chip mover"></i> Mover</span>
                                <span><i class="legend-chip wash"></i> Wash</span>
                                <span><i class="legend-chip bar"></i> LED Bar</span>
                            </div>
                        </div>
                        <canvas id="stage-canvas" width="1080" height="700"></canvas>
                        <div class="preview-footer">
                            <div>
                                <strong>Preview mode</strong>
                                <p>Local simulation only. No hardware output is sent from this screen.</p>
                            </div>
                            <div>
                                <strong>Live snapshot</strong>
                                <p id="runtime-summary">Waiting for control-plane state…</p>
                            </div>
                            <div>
                                <strong>Fixture Activity</strong>
                                <div id="fixture-activity" class="fixture-activity">
                                    Waiting for fixture output…
                                </div>
                            </div>
                        </div>
                    </section>

                    <section class="panel stack" aria-label="Operator workspace">
                        <div class="panel-header">
                            <h2>Operator Workspace</h2>
                            <p class="muted-small">Direct-select scene / safety / tag banks (Task 4 staging lane).</p>
                        </div>
                        <div id="operator-workspace" class="operator-workspace">
                            Loading workspace banks…
                        </div>
                    </section>

                    <section class="panel stack" aria-label="Inspector">
                        <div class="panel-header">
                            <h2>Fixture Inspector</h2>
                        </div>

                        <div id="fixture-inspector" class="inspector-empty">
                            Select a fixture to edit its mock parameters.
                        </div>

                        <details>
                            <summary><div class="subhead"><h3>Mock DMX Monitor</h3></div></summary>
                            <div class="details-body">
                                <div id="dmx-monitor" class="dmx-monitor"></div>
                            </div>
                        </details>
                    </section>

                    <section class="panel stack track-preview-panel" aria-label="Track preview">
                        <div class="panel-header wide">
                            <div>
                                <h2>Track Preview</h2>
                                <p>Scrub the waveform to jump the playhead. Full session audio, BPM, and section map.</p>
                            </div>
                        </div>
                        <div id="playback-panel" class="playback-panel empty">
                            Start a file-backed session with web mode to expose the current track here.
                        </div>
                    </section>

                    <section class="panel stack show-editor-panel" aria-label="Agentic show editor">
                        <div class="panel-header wide">
                            <div>
                                <h2>Agentic Show</h2>
                                <p>Imported from Rekordbox and editable as a phrase timeline.</p>
                            </div>
                            <div class="editor-status">
                                <span>Track-coupled phrase timeline</span>
                            </div>
                        </div>

                        <div id="show-editor" class="show-editor">
                            <div class="show-editor-empty">Start a file-backed session with web mode to expose the current track timeline here.</div>
                        </div>
                    </section>
                </main>
            </div>

            <script src="/static/mock_control_plane.js"></script>
        </body>
    </html>
    """


def create_app(
    services: ControlPlaneStateService | None = None,
    *,
    fixtures_dir: Path | None = None,
) -> Any:
    """Create the FastAPI control-plane application.

    `fixtures_dir` is the directory containing fixture profile YAMLs.
    Cycle-1 panel Codex H#3: this MUST match the runtime's effective
    `Settings.fixtures_dir` so the UI's profile dropdown lists the
    same profiles the graph will actually load. Default is `Settings()`'s
    default (`config/fixtures`); CLI passes the actual settings value.
    """
    if fixtures_dir is None:
        from photonic_synesthesia.core.config import Settings as _Settings
        fixtures_dir = _Settings().fixtures_dir
    fixtures_dir = Path(fixtures_dir)

    (
        FastAPI,
        HTTPException,
        WebSocket,
        WebSocketDisconnect,
        HTMLResponse,
        FileResponse,
        StaticFiles,
    ) = (
        _import_web_stack()
    )

    class ReleaseLeaseRequest(BaseModel):
        session_id: str
        force: bool = False

    class SessionEnvelope(BaseModel):
        issuer_id: str
        session_id: str
        role: OperatorRole = OperatorRole.OPERATOR

    class IntensityCommandRequest(SessionEnvelope):
        intensity: float

    class SpeedCommandRequest(SessionEnvelope):
        speed: float

    class SceneCommandRequest(SessionEnvelope):
        scene_id: str

    class MockFixtureCreateRequest(BaseModel):
        template_slug: str
        label: str | None = None

    class MockFixtureUpdateRequest(BaseModel):
        changes: dict[str, Any]

    class MockSceneStateRequest(BaseModel):
        scene_id: str

    class MockMasterStateRequest(BaseModel):
        master_intensity: float | None = None
        master_speed: float | None = None
        blackout: bool | None = None

    class PlaybackShowSectionUpdateRequest(BaseModel):
        changes: dict[str, Any]

    class PlaybackSeekRequest(BaseModel):
        seconds: float

    class PlaybackSelectionModeRequest(BaseModel):
        selection_mode: str

    class PlaybackSelectionVarianceRequest(BaseModel):
        selection_variance: float

    class PlaybackOperatorIntentRequest(BaseModel):
        intent: str
        scope: str = "track"
        target: str = "all"
        amount: float = 0.25
        expires_at: str | None = None

    class PlaybackProDJLinkTrackRequest(BaseModel):
        title: str
        artist: str | None = None
        duration_seconds: float | None = None
        expected_bpm: float | None = None
        playhead_seconds: float | None = None
        playing: bool | None = None
        finished: bool | None = None
        realtime: bool = True
        speed: float = 1.0
        selection_mode: str | None = None
        selection_variance: float | None = None

    class PlaybackStagedLookRequest(BaseModel):
        """Cycle-1 panel UF-11 preview-only contract: section_id required;
        partial cue_recipe / laser_program overrides are deep-merged into
        the authored section at commit time (cycle-1 panel UF-12)."""
        section_id: str
        cue_recipe: dict[str, Any]
        laser_program: dict[str, Any]

    app = FastAPI(
        title="Photonic Synesthesia Control Plane",
        version=__version__,
        summary="Control-plane service for live operation and future authoring flows.",
    )
    static_dir = Path(__file__).with_name("static")
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    services = services or get_shared_control_plane_service(create=True) or ControlPlaneStateService()
    app.state.services = services
    # Cycle-1 panel C1 + Phase A startup wiring: hydrate MockRigStore from
    # the active rig if one exists. `get_active_rig_name()` auto-clears a
    # stale pointer so we never crash on a missing target. Any load
    # failure (corrupt JSON, missing fixtures key, ValueError) is caught
    # and the canvas falls back to defaults.
    initial_fixtures: list[dict[str, Any]] | None = None
    active_rig_name = rig_storage.get_active_rig_name()
    if active_rig_name:
        try:
            initial_fixtures = list(rig_storage.load_rig(active_rig_name).get("fixtures", []) or [])
        except (FileNotFoundError, ValueError, KeyError, OSError) as exc:
            logger.warning(
                "active_rig_load_failed",
                name=active_rig_name,
                error=str(exc),
                fallback="default_rig",
            )
            initial_fixtures = None
    app.state.mock_rig = MockRigStore(initial_fixtures=initial_fixtures)
    app.state.fixtures_dir = fixtures_dir
    app.state.playback_context = get_shared_playback_context()
    mock_rig: MockRigStore = app.state.mock_rig

    def require_control(session_id: str) -> None:
        if not services.has_control(session_id):
            raise HTTPException(status_code=403, detail="Active control lease required")

    def accept_command(command: OperatorCommand) -> dict[str, Any]:
        receipt = services.accept_command(command)
        return {
            "receipt": receipt.model_dump(mode="json"),
            "snapshot": services.snapshot().model_dump(mode="json"),
        }

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return _render_control_plane_html()

    @app.get("/healthz")
    @log_endpoint("GET:/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/live/health")
    @log_endpoint("GET:/api/live/health")
    async def live_health() -> dict[str, Any]:
        return services.health(
            version=__version__,
            web_features=[
                "control_lease",
                "live_health",
                "live_snapshot",
                "live_safety",
                "mock_fixture_catalog",
                "mock_fixture_visualizer",
                "mock_rig_crud",
                "mock_universe_monitor",
                "websocket_live_feed",
            ],
        ).model_dump(mode="json")

    @app.get("/api/live/state")
    @log_endpoint("GET:/api/live/state")
    async def live_state() -> dict[str, Any]:
        services.publish_event(
            PlatformEventType.LIVE_STATE_PUBLISHED,
            "Live snapshot requested",
        )
        return services.snapshot().model_dump(mode="json")

    @app.get("/api/live/safety")
    @log_endpoint("GET:/api/live/safety")
    async def live_safety() -> dict[str, Any]:
        snapshot = services.snapshot()
        return {
            "blackout_active": snapshot.blackout_active,
            "armed_live": snapshot.armed_live,
            "safety_summary": snapshot.safety_summary.model_dump(mode="json"),
            "active_control_lease": snapshot.active_control_lease.model_dump(mode="json")
            if snapshot.active_control_lease
            else None,
            "recent_events": [event.model_dump(mode="json") for event in snapshot.recent_events],
        }

    @app.get("/api/mock/catalog")
    @log_endpoint("GET:/api/mock/catalog")
    async def mock_catalog() -> dict[str, Any]:
        return mock_rig.catalog()

    @app.get("/api/mock/state")
    @log_endpoint("GET:/api/mock/state")
    async def mock_state() -> dict[str, Any]:
        return mock_rig.snapshot()

    @app.get("/api/mock/universes")
    @log_endpoint("GET:/api/mock/universes")
    async def mock_universes() -> dict[str, Any]:
        return mock_rig.universe_snapshot()

    @app.get("/api/mock/playback")
    @log_endpoint("GET:/api/mock/playback")
    async def mock_playback() -> dict[str, Any]:
        playback_context: PlaybackContext | None = get_shared_playback_context()
        if playback_context is None:
            return {"available": False}
        return playback_context.snapshot()

    @app.get("/api/mock/playback/audio")
    @log_endpoint("GET:/api/mock/playback/audio")
    async def mock_playback_audio(session: str | None = None) -> Any:
        playback_context: PlaybackContext | None = get_shared_playback_context()
        if playback_context is None:
            raise HTTPException(status_code=404, detail="No playback file is active")
        if session is not None and session != playback_context.session_id:
            raise HTTPException(status_code=404, detail="Playback session is no longer active")
        media_path = Path(playback_context.file_path)
        if not media_path.is_file():
            raise HTTPException(status_code=404, detail="Playback file is missing")
        media_type = "audio/mpeg" if media_path.suffix.lower() == ".mp3" else None
        return FileResponse(
            media_path,
            media_type=media_type,
            headers={"Accept-Ranges": "bytes"},
        )

    @app.get("/api/mock/playback/ilda-export")
    @log_endpoint("GET:/api/mock/playback/ilda-export")
    async def mock_playback_ilda_export(session: str | None = None) -> Any:
        playback_context: PlaybackContext | None = get_shared_playback_context()
        if playback_context is None:
            raise HTTPException(status_code=404, detail="No playback file is active")
        if session is not None and session != playback_context.session_id:
            raise HTTPException(status_code=404, detail="Playback session is no longer active")
        export_path = Path(playback_context.ilda_export_path)
        if not playback_context.ilda_export_path or not export_path.is_file():
            raise HTTPException(status_code=404, detail="No ILDA export is available")
        media_type = "application/octet-stream"
        filename = export_path.name
        return FileResponse(export_path, media_type=media_type, filename=filename)

    @app.patch("/api/mock/playback/show-sections/{section_id}")
    @log_endpoint("PATCH:/api/mock/playback/show-sections/{section_id}")
    async def update_playback_show_section(
        section_id: str, request: PlaybackShowSectionUpdateRequest
    ) -> dict[str, Any]:
        playback_context: PlaybackContext | None = get_shared_playback_context()
        if playback_context is None:
            raise HTTPException(status_code=404, detail="No playback file is active")
        section = playback_context.update_show_section(section_id, request.changes)
        if section is None:
            raise HTTPException(status_code=404, detail="Show section not found")
        return playback_context.snapshot()

    @app.patch("/api/mock/playback/selection-mode")
    @log_endpoint("PATCH:/api/mock/playback/selection-mode")
    async def update_playback_selection_mode(
        request: PlaybackSelectionModeRequest,
    ) -> dict[str, Any]:
        """Cycle-3-rev-2 R2 fix (Kilo CRIT-2 + Codex HIGH + Gemini): the
        regen calls into AI scoring and was blocking the uvicorn worker
        thread on `future.result(timeout=5.0)`. The handler is `async def`,
        but a sync call inside an async function still consumes the
        thread for the duration. Bridge to asyncio properly via
        `run_in_executor` so the event loop can serve other requests
        (WebSocket frames, GET /api/mock/state, etc.) while the regen
        runs on the dedicated `_REGEN_EXECUTOR` thread.
        """
        playback_context: PlaybackContext | None = get_shared_playback_context()
        if playback_context is None:
            raise HTTPException(status_code=404, detail="No playback file is active")
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(
                None,  # default executor — the call is non-blocking; PlaybackContext serializes via _REGEN_INFLIGHT
                playback_context.set_selection_mode,
                request.selection_mode,
            )
        except RuntimeError as exc:
            # `regeneration already in flight` → 409 Conflict (cycle-3-rev-2 R7)
            # Other RuntimeErrors (timeout, invalid mode) → 400 Bad Request.
            status = 409 if "already in flight" in str(exc) else 400
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @app.patch("/api/mock/playback/selection-variance")
    @log_endpoint("PATCH:/api/mock/playback/selection-variance")
    async def update_playback_selection_variance(
        request: PlaybackSelectionVarianceRequest,
    ) -> dict[str, Any]:
        """Cycle-3-rev-2 R2: same pattern as selection-mode (regen is
        equally heavy)."""
        playback_context: PlaybackContext | None = get_shared_playback_context()
        if playback_context is None:
            raise HTTPException(status_code=404, detail="No playback file is active")
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(
                None,
                playback_context.set_selection_variance,
                request.selection_variance,
            )
        except RuntimeError as exc:
            status = 409 if "already in flight" in str(exc) else 400
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @app.post("/api/mock/playback/operator-intents")
    @log_endpoint("POST:/api/mock/playback/operator-intents")
    async def apply_playback_operator_intent(
        request: PlaybackOperatorIntentRequest,
    ) -> dict[str, Any]:
        playback_context: PlaybackContext | None = get_shared_playback_context()
        if playback_context is None:
            raise HTTPException(status_code=404, detail="No playback file is active")
        try:
            return playback_context.apply_operator_intent(
                intent=request.intent,
                scope=request.scope,
                target=request.target,
                amount=request.amount,
                expires_at=request.expires_at or "",
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/operator/workspace")
    @log_endpoint("GET:/api/operator/workspace")
    async def operator_workspace() -> dict[str, Any]:
        """Return the operator workspace banks + live active scene id.

        Cycle-3 panel 3C-H1: reads `operator_workspace_banks` (the
        cycle-2 cache key) — NOT `operator_workspace` (the cycle-1 key
        the cycle-2 plan accidentally still wrote into one snippet).
        Overlays `active_scene_id` from the snapshot's per-call live
        overlay so the UI renders the active scene button without
        depending on the authored cache.
        """
        playback_context: PlaybackContext | None = get_shared_playback_context()
        if playback_context is None:
            return {"banks": [], "active_scene_id": ""}
        snap = playback_context.snapshot()
        body = dict(snap.get("operator_workspace_banks") or {"banks": []})
        body["active_scene_id"] = snap.get("active_scene_id", "")
        return body

    @app.post("/api/operator/stage")
    @log_endpoint("POST:/api/operator/stage")
    async def stage_operator_look(
        request: PlaybackStagedLookRequest,
    ) -> dict[str, Any]:
        """Stage an operator look for preview (cycle-1 panel UF-11).

        Returns the staged_look dict. The runtime graph still reads
        authored `show_sections` only — the stage surfaces in
        `playback_snapshot["staged_look"]` for UI preview.
        """
        playback_context: PlaybackContext | None = get_shared_playback_context()
        if playback_context is None:
            raise HTTPException(status_code=404, detail="No playback session is active")
        try:
            return playback_context.set_staged_look(
                section_id=request.section_id,
                cue_recipe=request.cue_recipe,
                laser_program=request.laser_program,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/operator/commit")
    @log_endpoint("POST:/api/operator/commit")
    async def commit_operator_look() -> dict[str, Any]:
        """Commit the currently-staged look into the authored section.

        Cycle-1 panel UF-12 deep-merge: operator-supplied keys override
        authored values; every other authored field on the section
        survives. Cycle-1 panel SF-1: fails closed if the playhead
        advanced past the staged section's end (returns 409).
        """
        playback_context: PlaybackContext | None = get_shared_playback_context()
        if playback_context is None:
            raise HTTPException(status_code=404, detail="No playback session is active")
        try:
            return playback_context.commit_staged_look()
        except RuntimeError as exc:
            # "No staged look" → 400; "Playhead advanced past..." → 409.
            status = 409 if "playhead" in str(exc).lower() else 400
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @app.post("/api/mock/playback/pro-dj-link/track")
    @log_endpoint("POST:/api/mock/playback/pro-dj-link/track")
    async def bind_playback_pro_dj_link_track(
        request: PlaybackProDJLinkTrackRequest,
    ) -> dict[str, Any]:
        playback_context: PlaybackContext | None = get_shared_playback_context()
        if playback_context is None:
            raise HTTPException(status_code=404, detail="No playback session is active")
        try:
            return playback_context.bind_track_metadata(
                {
                    "track_title": request.title,
                    "track_artist": request.artist or "",
                    "duration_seconds": request.duration_seconds,
                    "expected_bpm": request.expected_bpm,
                    "playhead_seconds": request.playhead_seconds,
                    "playing": request.playing,
                    "finished": request.finished,
                    "realtime": request.realtime,
                    "speed": request.speed,
                    "selection_mode": request.selection_mode,
                    "selection_variance": request.selection_variance,
                    "metadata_source": "pro_dj_link",
                }
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/mock/playback/seek")
    @log_endpoint("POST:/api/mock/playback/seek")
    async def seek_playback(request: PlaybackSeekRequest) -> dict[str, Any]:
        playback_context: PlaybackContext | None = get_shared_playback_context()
        if playback_context is None:
            raise HTTPException(status_code=404, detail="No playback file is active")
        try:
            playback_context.request_seek(request.seconds)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return playback_context.snapshot()

    @app.post("/api/mock/fixtures")
    @log_endpoint("POST:/api/mock/fixtures")
    async def create_mock_fixture(request: MockFixtureCreateRequest) -> dict[str, Any]:
        if request.template_slug not in _FIXTURE_TEMPLATE_INDEX:
            raise HTTPException(status_code=404, detail="Unknown fixture template")
        fixture = mock_rig.create_fixture(request.template_slug, request.label)
        return {"fixture": fixture, "state": mock_rig.snapshot()}

    @app.patch("/api/mock/fixtures/{fixture_id}")
    @log_endpoint("PATCH:/api/mock/fixtures/{fixture_id}")
    async def update_mock_fixture(
        fixture_id: str, request: MockFixtureUpdateRequest
    ) -> dict[str, Any]:
        fixture = mock_rig.update_fixture(fixture_id, request.changes)
        if fixture is None:
            raise HTTPException(status_code=404, detail="Fixture not found")
        return {"fixture": fixture, "state": mock_rig.snapshot()}

    @app.post("/api/mock/fixtures/{fixture_id}/duplicate")
    @log_endpoint("POST:/api/mock/fixtures/{fixture_id}/duplicate")
    async def duplicate_mock_fixture(fixture_id: str) -> dict[str, Any]:
        fixture = mock_rig.duplicate_fixture(fixture_id)
        if fixture is None:
            raise HTTPException(status_code=404, detail="Fixture not found")
        return {"fixture": fixture, "state": mock_rig.snapshot()}

    @app.delete("/api/mock/fixtures/{fixture_id}")
    @log_endpoint("DELETE:/api/mock/fixtures/{fixture_id}")
    async def delete_mock_fixture(fixture_id: str) -> dict[str, Any]:
        if not mock_rig.delete_fixture(fixture_id):
            raise HTTPException(status_code=404, detail="Fixture not found")
        return {"deleted": True, "state": mock_rig.snapshot()}

    # ------------------------------------------------------------------
    # Rig storage (Phase A — named rig presets)
    #
    # Cycle-1 panel resolution:
    #   - C1: get_active_rig_name auto-clears stale pointers; load_rig
    #     wrapped in try/except at every read site; missing files surface
    #     as 404 not 500.
    #   - H1: rig_storage._validate_name enforced AT THE STORAGE LAYER
    #     (not just UI); reserved names rejected by the function itself.
    #   - H2: A8 literal-1 fallback enforced inside load_rig; pinned by
    #     test_load_rig_missing_schema_key_treated_as_v1...
    #   - H4: empty-materialize policy decided by Phase B caller, not
    #     this module.
    #   - H5: profile/enabled persistence is closed by the elif branches
    #     added to MockRigStore.update_fixture above.
    #   - A10: PUT strips client-supplied schema_version/saved_at via
    #     rig_storage._strip_server_fields; re-stamps server-side.

    class RigPutRequest(BaseModel):
        # Round-trip-symmetric (closes Codex H#2): accepts the same
        # shape GET returns. Server-stamped fields (`_schema_version`,
        # `saved_at`) are stripped + re-stamped (closes A10).
        fixtures: list[dict[str, Any]]

    def _conflicts_to_payload(rig_fixtures: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Run conflict detection against `app.state.fixtures_dir` and
        return a JSON-serializable list (empty = clean)."""
        return [
            {
                "universe": c.universe,
                "channel": c.channel,
                "fixture_a_id": c.fixture_a_id,
                "fixture_b_id": c.fixture_b_id,
                "description": c.describe(),
            }
            for c in rig_storage.detect_address_conflicts(rig_fixtures, fixtures_dir)
        ]

    def _bad_request(detail: str, **extra: Any) -> "HTTPException":
        # Helper for 400 with structured body.
        body = {"detail": detail, **extra}
        return HTTPException(status_code=400, detail=body)

    @app.get("/api/mock/rigs")
    @log_endpoint("GET:/api/mock/rigs")
    async def list_mock_rigs() -> dict[str, Any]:
        return {
            "rigs": rig_storage.list_rigs(),
            "active": rig_storage.get_active_rig_name(),
        }

    @app.get("/api/mock/rigs/{name}")
    @log_endpoint("GET:/api/mock/rigs/{name}")
    async def get_mock_rig(name: str) -> dict[str, Any]:
        try:
            rig_storage._validate_name(name)
        except ValueError as exc:
            raise _bad_request("invalid_rig_name", reason=str(exc))
        try:
            rig = rig_storage.load_rig(name)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="rig_not_found")
        except ValueError as exc:
            # Includes "schema newer than build" → 422 to distinguish from
            # malformed-on-disk; both are unrecoverable for this build.
            msg = str(exc)
            if "newer than this build" in msg:
                raise HTTPException(status_code=422, detail={"detail": "schema_too_new", "reason": msg})
            raise _bad_request("rig_corrupt", reason=msg)
        rig["conflicts"] = _conflicts_to_payload(rig.get("fixtures", []))
        return rig

    @app.put("/api/mock/rigs/{name}")
    @log_endpoint("PUT:/api/mock/rigs/{name}")
    async def put_mock_rig(name: str, request: RigPutRequest) -> dict[str, Any]:
        try:
            rig_storage._validate_name(name)
        except ValueError as exc:
            raise _bad_request("invalid_rig_name", reason=str(exc))
        # Strip client-supplied server fields (closes A10). Note the
        # request model already lacks those keys, but defensive in case
        # the schema is later loosened.
        fixtures = list(request.fixtures or [])
        try:
            saved_path = rig_storage.save_rig(name, fixtures)
        except ValueError as exc:
            msg = str(exc)
            if "MUST have a non-null profile" in msg:
                raise _bad_request("type_profile_required", reason=msg)
            if "duplicate fixture id" in msg:
                raise _bad_request("duplicate_fixture_id", reason=msg)
            raise _bad_request("rig_invalid", reason=msg)
        rig = rig_storage.load_rig(name)
        rig["conflicts"] = _conflicts_to_payload(rig.get("fixtures", []))
        rig["saved_path"] = str(saved_path)
        return rig

    @app.post("/api/mock/rigs/{name}/snapshot")
    @log_endpoint("POST:/api/mock/rigs/{name}/snapshot")
    async def snapshot_mock_rig(name: str) -> dict[str, Any]:
        """Cycle-1 panel Codex H#2: separate from PUT. This is the
        "save what's currently on the canvas" path. UI's [Save] button
        calls this; PUT is for explicit document upload."""
        try:
            rig_storage._validate_name(name)
        except ValueError as exc:
            raise _bad_request("invalid_rig_name", reason=str(exc))
        fixtures = mock_rig.dump()
        try:
            saved_path = rig_storage.save_rig(name, fixtures)
        except ValueError as exc:
            msg = str(exc)
            if "MUST have a non-null profile" in msg:
                raise _bad_request("type_profile_required", reason=msg)
            if "duplicate fixture id" in msg:
                raise _bad_request("duplicate_fixture_id", reason=msg)
            raise _bad_request("rig_invalid", reason=msg)
        rig = rig_storage.load_rig(name)
        rig["conflicts"] = _conflicts_to_payload(rig.get("fixtures", []))
        rig["saved_path"] = str(saved_path)
        return rig

    @app.post("/api/mock/rigs/{name}/load")
    @log_endpoint("POST:/api/mock/rigs/{name}/load")
    async def load_mock_rig(name: str) -> dict[str, Any]:
        try:
            rig_storage._validate_name(name)
        except ValueError as exc:
            raise _bad_request("invalid_rig_name", reason=str(exc))
        try:
            rig = rig_storage.load_rig(name)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="rig_not_found")
        except ValueError as exc:
            raise _bad_request("rig_corrupt", reason=str(exc))
        try:
            mock_rig.replace_all(rig.get("fixtures", []) or [])
        except ValueError as exc:
            raise _bad_request("rig_fixtures_invalid", reason=str(exc))
        # Cycle-1 panel Claude M5: response includes `clear_selection: true`
        # so the UI knows to drop selectedFixtureId + pending PATCH timers.
        return {
            "loaded": name,
            "state": mock_rig.snapshot(),
            "clear_selection": True,
            "conflicts": _conflicts_to_payload(rig.get("fixtures", [])),
        }

    @app.post("/api/mock/rigs/{name}/activate")
    @log_endpoint("POST:/api/mock/rigs/{name}/activate")
    async def activate_mock_rig(name: str) -> dict[str, Any]:
        try:
            rig_storage._validate_name(name)
        except ValueError as exc:
            raise _bad_request("invalid_rig_name", reason=str(exc))
        try:
            rig_storage.set_active_rig(name)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="rig_not_found")
        return {"active": name}

    from fastapi import Header, Query as _Query  # local — fastapi is optional at module level

    @app.post("/api/mock/rigs/{name}/duplicate")
    @log_endpoint("POST:/api/mock/rigs/{name}/duplicate")
    async def duplicate_mock_rig(
        name: str,
        # Query alias so the wire param is `?as=<newname>` (the Python name
        # `as` is a reserved word, so we bind to `as_name` and alias).
        as_name: str = _Query(default="", alias="as"),
    ) -> dict[str, Any]:
        try:
            rig_storage._validate_name(name)
        except ValueError as exc:
            raise _bad_request("invalid_rig_name", reason=str(exc))
        if not as_name:
            raise _bad_request("missing_as_name", reason="?as=<newname> query param required")
        try:
            rig_storage._validate_name(as_name)
        except ValueError as exc:
            raise _bad_request("invalid_rig_name", reason=str(exc))
        # Post-merge cycle-4 audit M2 (self): duplicate-to-self would
        # silently overwrite the source rig's `saved_at` timestamp under
        # the disguise of a "duplicate" action. Reject so the user isn't
        # surprised when their source rig's timestamp jumps.
        if as_name == name:
            raise _bad_request(
                "duplicate_to_self",
                reason="target name must differ from source",
            )
        try:
            source = rig_storage.load_rig(name)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="rig_not_found")
        try:
            rig_storage.save_rig(as_name, source.get("fixtures", []))
        except ValueError as exc:
            raise _bad_request("rig_invalid", reason=str(exc))
        return {"duplicated_to": as_name}

    @app.delete("/api/mock/rigs/{name}")
    @log_endpoint("DELETE:/api/mock/rigs/{name}")
    async def delete_mock_rig(name: str, force: bool = False) -> dict[str, Any]:
        try:
            rig_storage._validate_name(name)
        except ValueError as exc:
            raise _bad_request("invalid_rig_name", reason=str(exc))
        active_before = rig_storage.get_active_rig_name()
        if name == active_before and not force:
            raise HTTPException(
                status_code=409,
                detail={
                    "detail": "rig_is_active",
                    "reason": "Use ?force=true to delete the active rig (active pointer will be cleared atomically).",
                },
            )
        deleted = rig_storage.delete_rig(name, force=force)
        if not deleted:
            raise HTTPException(status_code=404, detail="rig_not_found")
        return {"deleted": name, "active": rig_storage.get_active_rig_name()}

    @app.get("/api/mock/fixture-profiles")
    @log_endpoint("GET:/api/mock/fixture-profiles")
    async def list_fixture_profiles() -> dict[str, Any]:
        # Cycle-1 panel Codex H#3: uses the same fixtures_dir the runtime
        # graph reads, so the dropdown CANNOT list profiles the runtime
        # won't actually load.
        return {
            "profiles": rig_storage.list_available_profiles(fixtures_dir),
            "fixtures_dir": str(fixtures_dir),
        }

    @app.post("/api/mock/scene")
    @log_endpoint("POST:/api/mock/scene")
    async def update_mock_scene(request: MockSceneStateRequest) -> dict[str, Any]:
        if not mock_rig.update_scene(request.scene_id):
            raise HTTPException(status_code=404, detail="Unknown mock scene")
        return mock_rig.snapshot()

    @app.post("/api/mock/masters")
    @log_endpoint("POST:/api/mock/masters")
    async def update_mock_masters(request: MockMasterStateRequest) -> dict[str, Any]:
        return mock_rig.update_masters(
            master_intensity=request.master_intensity,
            master_speed=request.master_speed,
            blackout=request.blackout,
        )

    @app.post("/api/control/lease/acquire")
    @log_endpoint("POST:/api/control/lease/acquire")
    async def acquire_control_lease(
        request: LeaseAcquireRequest,
        x_force_takeover_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        # Cycle-5 CRITICAL (SECURE): force-takeover requires the
        # X-Force-Takeover-Token header matching the server's
        # PHOTONIC_FORCE_TAKEOVER_TOKEN env var. If the env var is
        # unset, all force-takeover requests fail closed.
        response = services.acquire_control_lease(
            request, force_token=x_force_takeover_token,
        )
        return response.model_dump(mode="json")

    @app.post("/api/control/lease/release")
    @log_endpoint("POST:/api/control/lease/release")
    async def release_control_lease(request: ReleaseLeaseRequest) -> dict[str, Any]:
        released = services.release_control_lease(request.session_id, force=request.force)
        if not released:
            raise HTTPException(status_code=404, detail="No matching control lease to release")
        return {
            "released": True,
            "active_control_lease": None,
        }

    @app.post("/api/control/arm")
    @log_endpoint("POST:/api/control/arm")
    async def arm_live(request: SessionEnvelope) -> dict[str, Any]:
        require_control(request.session_id)
        return accept_command(
            OperatorCommand(
                issuer_id=request.issuer_id,
                session_id=request.session_id,
                role=request.role,
                command_type=CommandType.ARM,
            )
        )

    @app.post("/api/control/disarm")
    @log_endpoint("POST:/api/control/disarm")
    async def disarm_live(request: SessionEnvelope) -> dict[str, Any]:
        require_control(request.session_id)
        return accept_command(
            OperatorCommand(
                issuer_id=request.issuer_id,
                session_id=request.session_id,
                role=request.role,
                command_type=CommandType.DISARM,
            )
        )

    @app.post("/api/control/blackout")
    @log_endpoint("POST:/api/control/blackout")
    async def activate_blackout(request: SessionEnvelope) -> dict[str, Any]:
        require_control(request.session_id)
        return accept_command(
            OperatorCommand(
                issuer_id=request.issuer_id,
                session_id=request.session_id,
                role=request.role,
                command_type=CommandType.BLACKOUT,
            )
        )

    @app.post("/api/control/clear-blackout")
    @log_endpoint("POST:/api/control/clear-blackout")
    async def clear_blackout(request: SessionEnvelope) -> dict[str, Any]:
        require_control(request.session_id)
        return accept_command(
            OperatorCommand(
                issuer_id=request.issuer_id,
                session_id=request.session_id,
                role=request.role,
                command_type=CommandType.CLEAR_BLACKOUT,
            )
        )

    @app.post("/api/control/intensity")
    @log_endpoint("POST:/api/control/intensity")
    async def set_intensity(request: IntensityCommandRequest) -> dict[str, Any]:
        require_control(request.session_id)
        return accept_command(
            OperatorCommand(
                issuer_id=request.issuer_id,
                session_id=request.session_id,
                role=request.role,
                command_type=CommandType.SET_GLOBAL_INTENSITY,
                payload={"intensity": request.intensity},
            )
        )

    @app.post("/api/control/speed")
    @log_endpoint("POST:/api/control/speed")
    async def set_speed(request: SpeedCommandRequest) -> dict[str, Any]:
        require_control(request.session_id)
        return accept_command(
            OperatorCommand(
                issuer_id=request.issuer_id,
                session_id=request.session_id,
                role=request.role,
                command_type=CommandType.SET_GLOBAL_SPEED,
                payload={"speed": request.speed},
            )
        )

    @app.post("/api/control/scenes/launch")
    @log_endpoint("POST:/api/control/scenes/launch")
    async def launch_scene(request: SceneCommandRequest) -> dict[str, Any]:
        require_control(request.session_id)
        return accept_command(
            OperatorCommand(
                issuer_id=request.issuer_id,
                session_id=request.session_id,
                role=request.role,
                command_type=CommandType.LAUNCH_SCENE,
                payload={"scene_id": request.scene_id},
            )
        )

    @app.post("/api/control/scenes/hold")
    @log_endpoint("POST:/api/control/scenes/hold")
    async def hold_scene(request: SceneCommandRequest) -> dict[str, Any]:
        require_control(request.session_id)
        return accept_command(
            OperatorCommand(
                issuer_id=request.issuer_id,
                session_id=request.session_id,
                role=request.role,
                command_type=CommandType.HOLD_SCENE,
                payload={"scene_id": request.scene_id},
            )
        )

    @app.post("/api/control/scenes/release-hold")
    @log_endpoint("POST:/api/control/scenes/release-hold")
    async def release_scene_hold(request: SessionEnvelope) -> dict[str, Any]:
        require_control(request.session_id)
        return accept_command(
            OperatorCommand(
                issuer_id=request.issuer_id,
                session_id=request.session_id,
                role=request.role,
                command_type=CommandType.RELEASE_SCENE_HOLD,
            )
        )

    @app.websocket("/ws/live")
    async def websocket_live(websocket: WebSocket) -> None:
        await websocket.accept()
        # Cycle-4 Review B LOW-2: ping/pong to detect half-open TCP
        # connections (network partition, laptop sleep, NAT table
        # eviction). Without this, a dead connection is only discovered
        # when a `send_json` hits the 5s timeout, which can leave the
        # client seeing stale data for up to 5s after the link drops.
        # Ping interval 30s matches the socket's starlette default and
        # is well under most NAT idle timeouts (60-120s).
        last_ping = time.time()
        PING_INTERVAL_S = 30.0
        try:
            while True:
                # Cycle-4 CRITICAL-5: timeout-bounded send.
                try:
                    await asyncio.wait_for(
                        websocket.send_json(
                            services.snapshot().model_dump(mode="json")
                        ),
                        timeout=5.0,
                    )
                except asyncio.TimeoutError:
                    logger.warning("ws_live_send_timeout")
                    break

                # Cycle-4 LOW-2: periodic application-level ping. We send
                # a small JSON `{"op": "ping", "ts": ...}` frame — simpler
                # than starlette's built-in ping (which requires passing
                # through to the underlying protocol) and gives us an
                # explicit pong handshake we can observe in application logs.
                now = time.time()
                if now - last_ping >= PING_INTERVAL_S:
                    try:
                        await asyncio.wait_for(
                            websocket.send_json({"op": "ping", "ts": now}),
                            timeout=5.0,
                        )
                        last_ping = now
                    except asyncio.TimeoutError:
                        logger.warning("ws_live_ping_timeout")
                        break

                await asyncio.sleep(1.0)
        except WebSocketDisconnect:
            return

    return app


def main() -> None:
    """Run the control-plane service."""
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - exercised only in minimal envs
        sys.stderr.write("uvicorn is required for `photonic-web`. Install with `pip install -e '.[web]'`.\n")
        raise SystemExit(1) from exc

    app = create_app()
    host = os.getenv("PHOTONIC_WEB_HOST", "127.0.0.1")
    port = int(os.getenv("PHOTONIC_WEB_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)


def serve_in_thread(
    *,
    services: ControlPlaneStateService | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
    fixtures_dir: Path | None = None,
) -> tuple[Any, threading.Thread]:
    """Start the control-plane app in a background thread.

    Cycle-1 panel Codex H#3: `fixtures_dir` is plumbed through so the
    web UI's profile dropdown lists the same profiles the runtime graph
    will load. CLI passes `settings.fixtures_dir`.
    """
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - exercised only in minimal envs
        raise RuntimeError(
            "uvicorn is required for embedded web serving. Install with: pip install -e '.[web]'"
        ) from exc

    app = create_app(services=services, fixtures_dir=fixtures_dir)
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="photonic-web", daemon=True)
    thread.start()

    # Cycle-6 E5/H7: every error path between here and the successful
    # `return` below MUST tear down `server` + `thread`. Pre-E5 a
    # bind failure or startup timeout raised a RuntimeError without
    # calling `shutdown_server`, leaving the daemon uvicorn thread
    # running until process exit. With cycle-6 E2's tight leak canary
    # active, that's a hard test failure too — but the operational
    # impact is worse: the port stays bound, blocking the retry path
    # that the operator inevitably attempts after fixing whatever
    # caused the initial failure.
    try:
        deadline = time.time() + 5.0
        while not server.started:
            if not thread.is_alive():
                raise RuntimeError("Embedded web server terminated before startup completed")
            if time.time() >= deadline:
                raise RuntimeError("Timed out waiting for embedded web server startup")
            time.sleep(0.05)

        # Ensure the port is actually accepting connections before returning.
        while time.time() < deadline:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.2)
                if sock.connect_ex((host, port)) == 0:
                    break
            time.sleep(0.05)
    except BaseException:
        # Tear down the daemon thread before re-raising. `shutdown_server`
        # is the single canonical teardown path; no need to duplicate
        # its should_exit / force_exit / join logic here.
        try:
            shutdown_server(server, thread, soft_timeout=2.0, force_timeout=1.0)
        except Exception:  # pragma: no cover — defensive
            pass
        raise

    return server, thread


def shutdown_server(
    server: Any,
    thread: threading.Thread | None,
    *,
    soft_timeout: float = 5.0,
    force_timeout: float = 2.0,
) -> None:
    """Cleanly stop an embedded uvicorn server started via serve_in_thread.

    Cycle-6 A4: three-phase shutdown so a hung request or websocket
    can't wedge the main process.

      1. Soft: set `should_exit`. Uvicorn finishes in-flight requests
         and closes listeners. Join with `soft_timeout`.
      2. Hard: if the thread is still alive, set `force_exit` so
         uvicorn aborts active connections. Join with `force_timeout`.
      3. Loud: if the thread is STILL alive, log a warning. The
         thread is a daemon so the process can still exit, but a
         future incarnation of yesterday's crash class would be
         visible in logs instead of silent.

    Safe to call with None for either argument (no-op).
    """
    if server is None or thread is None or not thread.is_alive():
        return

    server.should_exit = True
    thread.join(timeout=soft_timeout)
    if not thread.is_alive():
        return

    logger.warning(
        "embedded_web_server_soft_shutdown_timed_out",
        soft_timeout=soft_timeout,
    )
    server.force_exit = True
    thread.join(timeout=force_timeout)
    if thread.is_alive():
        logger.error(
            "embedded_web_server_failed_to_exit",
            total_timeout=soft_timeout + force_timeout,
        )
