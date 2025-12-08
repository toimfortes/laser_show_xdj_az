"""
Scene Selection Node: AI-driven scene selection based on fused state.

Maps musical structure, energy levels, and DJ intent to lighting scenes.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, Any, Optional, List
import json
import structlog

from photonic_synesthesia.core.state import PhotonicState, MusicStructure, SceneState
from photonic_synesthesia.core.config import SceneConfig

logger = structlog.get_logger()


class SceneSelectNode:
    """
    Selects appropriate lighting scene based on current state.

    Uses a priority-based system:
    1. MIDI pad triggers (manual override - highest priority)
    2. Drop detection (immediate high-energy response)
    3. Structure-based selection (buildup, breakdown, etc.)
    4. Energy-based fallback
    """

    def __init__(self, config: SceneConfig):
        self.config = config
        self.scenes: Dict[str, Any] = {}
        self.pad_overrides: Dict[int, str] = {}

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
            MusicStructure.UNKNOWN: "idle",
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

        # =================================================================
        # Priority 1: MIDI Pad Override
        # =================================================================
        pad_triggers = state["midi_state"]["pad_triggers"]
        for pad in pad_triggers:
            if pad in self.pad_overrides:
                pending_scene = self.pad_overrides[pad]
                logger.info("Pad override triggered", pad=pad, scene=pending_scene)
                break

        # =================================================================
        # Priority 2: Drop Detection
        # =================================================================
        if pending_scene is None:
            if state["current_structure"] == MusicStructure.DROP:
                pending_scene = "drop_intense"
            elif state["drop_probability"] > 0.9:
                # Pre-load drop scene
                pending_scene = "drop_intense"

        # =================================================================
        # Priority 3: Structure-Based Selection
        # =================================================================
        if pending_scene is None:
            structure = state["current_structure"]
            pending_scene = self.structure_scenes.get(structure, "idle")

        # =================================================================
        # Priority 4: Energy-Based Adjustment
        # =================================================================
        energy = state["audio_features"]["rms_energy"]
        if pending_scene and pending_scene in self.scenes:
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
                transition_time = self.config.transition_time_s
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

        # Record processing time
        state["processing_times"]["scene_select"] = time.time() - start_time

        return state

    def get_scene_data(self, scene_name: str) -> Optional[Dict[str, Any]]:
        """Get full scene definition by name."""
        return self.scenes.get(scene_name)

    def list_scenes(self) -> List[str]:
        """List all available scene names."""
        return list(self.scenes.keys())
