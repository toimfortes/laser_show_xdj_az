"""Scene Selection Node: AI-driven scene selection based on fused state.

Maps musical structure, energy levels, and DJ intent to lighting scenes.
"""

from __future__ import annotations

import json
import time
from typing import Any

from photonic_synesthesia.core.config import SceneConfig
from photonic_synesthesia.core.logging import get_logger
from photonic_synesthesia.core.state import MusicStructure, PhotonicState, SceneState
from photonic_synesthesia.graph.nodes.section_dynamics import resolve_active_section_dynamics

logger = get_logger(__name__)


class SceneSelectNode:
    """
    Selects appropriate lighting scene based on current state.

    The director provides the target scene. This node applies operator
    overrides and transition constraints, then falls back only when needed.
    """

    def __init__(self, config: SceneConfig):
        self.config = config
        self.scenes: dict[str, Any] = {}
        self.pad_overrides: dict[int, str] = {}

        # Load scene definitions
        self._load_scenes()

        # Default scene mappings
        self.structure_scenes = {
            MusicStructure.INTRO: "intro_ambient",
            MusicStructure.VERSE: "verse_rhythmic",
            MusicStructure.BUILDUP: "buildup_tension",
            MusicStructure.DROP: "drop_intense",
            MusicStructure.BREAKDOWN: "breakdown_ambient",
            MusicStructure.OUTRO: "outro_fade",
            MusicStructure.UNKNOWN: self.config.default_scene,
        }

    def _load_scenes(self) -> None:
        """Load scene definitions from config directory."""
        scenes_dir = self.config.scenes_dir

        if not scenes_dir.exists():
            logger.warning("Scenes directory not found", path=str(scenes_dir))
            return

        for scene_file in scenes_dir.glob("*.json"):
            try:
                with open(scene_file) as f:
                    scene_data = json.load(f)
                scene_name = scene_data.get("name", scene_file.stem)
                self.scenes[scene_name] = scene_data
                logger.debug("Loaded scene", name=scene_name)
            except Exception as e:
                logger.error("Failed to load scene", file=str(scene_file), error=str(e))

        # Load pad override mappings if present
        for name, scene in self.scenes.items():
            if "pad_trigger" in scene:
                self.pad_overrides[scene["pad_trigger"]] = name

    def __call__(self, state: PhotonicState) -> PhotonicState:
        """Select scene and update state."""
        start_time = time.time()
        current_time = state["timestamp"]

        current_scene = state["scene_state"]["current_scene"]
        pending_scene = None
        transition_progress = state["scene_state"]["transition_progress"]
        control_state = state["control_state"]

        # =================================================================
        # Priority 0: Control Plane Scene Hold / Launch
        # =================================================================
        held_scene = control_state["scene_hold"]
        launched_scene = control_state["launched_scene"]
        if held_scene:
            pending_scene = held_scene
        elif launched_scene:
            pending_scene = launched_scene

        # =================================================================
        # Priority 1: MIDI Pad Override
        # =================================================================
        if pending_scene is None:
            pad_triggers = state["midi_state"]["pad_triggers"]
            for pad in pad_triggers:
                if pad in self.pad_overrides:
                    pending_scene = self.pad_overrides[pad]
                    logger.info("Pad override triggered", pad=pad, scene=pending_scene)
                    break

        # =================================================================
        # Priority 2: Authored active-section scene override
        # =================================================================
        if pending_scene is None:
            dynamics = resolve_active_section_dynamics(state)
            section_scene_id = dynamics.get("scene_id")
            allow_transition = bool(
                state.get("director_state", {}).get("allow_scene_transition", True)
            )
            if section_scene_id and self._is_valid_scene_name(section_scene_id):
                if allow_transition or section_scene_id == current_scene:
                    pending_scene = section_scene_id
                else:
                    logger.debug(
                        "Active section scene transition gated off",
                        scene_id=section_scene_id,
                        current_scene=current_scene,
                        section_id=dynamics.get("section_id"),
                    )
            elif section_scene_id:
                logger.debug(
                    "Active section scene not found in catalog",
                    scene_id=section_scene_id,
                    section_id=dynamics.get("section_id"),
                )

        # =================================================================
        # Priority 3: Director-directed transition (single source of target scene)
        # =================================================================
        if pending_scene is None:
            director = state.get("director_state")
            if director:
                proposed = str(director["target_scene"])
                allow_transition = bool(director.get("allow_scene_transition", True))
                if proposed in self.scenes and (
                    allow_transition or proposed == current_scene
                ):
                    pending_scene = proposed
                elif not self._is_valid_scene_name(proposed):
                    logger.debug(
                        "Director proposed scene not found in catalog",
                        proposed=proposed,
                    )
                    if allow_transition:
                        pending_scene = self.structure_scenes.get(
                            state["current_structure"],
                            self.config.default_scene,
                        )
                    else:
                        pending_scene = current_scene
                elif not allow_transition:
                    pending_scene = current_scene

        # =================================================================
        # Priority 4: Structure-based fallback
        # =================================================================
        if pending_scene is None:
            pending_scene = self.structure_scenes.get(
                state["current_structure"],
                self.config.default_scene,
            )

        # Validate fallback scenes to avoid invalid transitions into deleted scene files.
        if not self._is_valid_scene_name(pending_scene):
            pending_scene = self._resolve_fallback_scene(state["current_structure"])

        # =================================================================
        # Priority 5: Energy-based adjustment
        # =================================================================
        energy = state["audio_features"]["rms_energy"]
        if pending_scene and pending_scene != current_scene and pending_scene in self.scenes:
            scene_data = self.scenes[pending_scene]
            # Check energy thresholds
            min_energy = scene_data.get("triggers", {}).get("energy_threshold", 0)
            if energy < min_energy * 0.5:
                # Energy too low for this scene, use a calmer version
                calm_variant = f"{pending_scene}_calm"
                if calm_variant in self.scenes:
                    pending_scene = calm_variant

        # =================================================================
        # Scene Transition Logic
        # =================================================================
        if pending_scene != current_scene:
            if state["scene_state"]["pending_scene"] != pending_scene:
                # New scene requested - start transition
                state["scene_state"]["pending_scene"] = pending_scene
                state["scene_state"]["transition_start_time"] = current_time
                transition_progress = 0.0
            else:
                # Continue existing transition
                speed_scalar = max(0.1, float(control_state["global_speed"]))
                transition_time = self.config.transition_time_s / speed_scalar
                elapsed = current_time - state["scene_state"]["transition_start_time"]
                transition_progress = min(1.0, elapsed / transition_time)

                if transition_progress >= 1.0:
                    # Transition complete
                    current_scene = pending_scene
                    state["scene_state"]["current_scene"] = current_scene
                    state["scene_state"]["pending_scene"] = None
                    state["scene_state"]["scene_start_time"] = current_time
                    logger.info("Scene transition complete", scene=current_scene)
        else:
            # No change needed
            pending_scene = None
            transition_progress = 0.0

        # Update state
        state["scene_state"] = SceneState(
            current_scene=current_scene,
            pending_scene=pending_scene,
            transition_progress=transition_progress,
            transition_start_time=state["scene_state"]["transition_start_time"],
            scene_start_time=state["scene_state"]["scene_start_time"],
        )

        # =================================================================
        # Apply Scene Overrides to Director State
        # =================================================================
        # Scenes may carry a "director_overrides" block that patches a
        # small whitelisted set of DirectorState fields after
        # director_intent has run. Whitelisting keeps the TypedDict
        # contract intact (mypy won't accept dynamic key assignment on a
        # TypedDict) and prevents scene JSON from mutating unrelated
        # director state.
        _OVERRIDABLE_KEYS = {
            "color_theme",
            "movement_style",
            "laser_aggression",
            "color_drive",
            "laser_motion_energy",
            "laser_color_energy",
            "strobe_budget_hz",
        }
        if current_scene in self.scenes:
            overrides = self.scenes[current_scene].get("director_overrides", {})
            if overrides:
                director_state = state["director_state"]
                for key, value in overrides.items():
                    if key not in _OVERRIDABLE_KEYS:
                        continue
                    if key == "color_theme":
                        director_state["color_theme"] = str(value)
                    elif key == "movement_style":
                        director_state["movement_style"] = str(value)
                    elif key == "laser_aggression":
                        director_state["laser_aggression"] = float(value)
                    elif key == "color_drive":
                        director_state["color_drive"] = float(value)
                    elif key == "laser_motion_energy":
                        director_state["laser_motion_energy"] = float(value)
                    elif key == "laser_color_energy":
                        director_state["laser_color_energy"] = float(value)
                    elif key == "strobe_budget_hz":
                        director_state["strobe_budget_hz"] = float(value)
                    logger.debug("Applied scene override", key=key, value=value)

        # Record processing time
        state["processing_times"]["scene_select"] = time.time() - start_time

        return state

    def _is_valid_scene_name(self, scene_name: str) -> bool:
        return scene_name in self.scenes

    def _resolve_fallback_scene(self, structure: MusicStructure) -> str:
        """Return best-known fallback scene for this structure/current config."""
        if not self.scenes:
            return self.config.default_scene

        fallback = self.structure_scenes.get(structure, self.config.default_scene)
        if fallback in self.scenes:
            return fallback

        for candidate in (self.config.default_scene, "idle"):
            if candidate in self.scenes:
                return candidate

        return sorted(self.scenes)[0]

    def get_scene_data(self, scene_name: str) -> dict[str, Any] | None:
        """Get full scene definition by name."""
        return self.scenes.get(scene_name)

    def list_scenes(self) -> list[str]:
        """List all available scene names."""
        return list(self.scenes.keys())
