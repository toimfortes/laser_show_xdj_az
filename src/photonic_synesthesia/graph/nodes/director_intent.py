"""Director intent node."""

from __future__ import annotations

import time

from photonic_synesthesia.core.state import DirectorState, PhotonicState
from photonic_synesthesia.director import DirectorEngine


class DirectorIntentNode:
    """Generate high-level show intent from fused state."""

    def __init__(self, engine: DirectorEngine | None = None):
        self.engine = engine or DirectorEngine()

    def __call__(self, state: PhotonicState) -> PhotonicState:
        start_time = time.time()
        decision = self.engine.decide(state)

        state["director_state"] = DirectorState(
            target_scene=decision.target_scene,
            energy_level=decision.energy_level,
            color_theme=decision.color_theme,
            movement_style=decision.movement_style,
            strobe_budget_hz=decision.strobe_budget_hz,
            melodic_smoothness=decision.melodic_smoothness,
            laser_aggression=decision.laser_aggression,
            color_drive=decision.color_drive,
            laser_motion_energy=decision.laser_motion_energy,
            laser_color_energy=decision.laser_color_energy,
            phrase_role=decision.phrase_role,
            subphrase_role=decision.subphrase_role,
            fill_pressure=decision.fill_pressure,
            phrase_intensity=decision.phrase_intensity,
            allow_scene_transition=decision.allow_scene_transition,
        )

        state["processing_times"]["director_intent"] = time.time() - start_time
        return state
