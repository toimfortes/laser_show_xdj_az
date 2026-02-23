"""Interpreter node that constrains fixture commands."""

from __future__ import annotations

import time

from photonic_synesthesia.core.config import SafetyConfig
from photonic_synesthesia.core.state import PhotonicState
from photonic_synesthesia.interpreters import SafetyConstraintInterpreter


class InterpreterNode:
    """Apply safety and smoothness constraints before DMX output."""

    def __init__(self, safety: SafetyConfig, max_delta_per_frame: int = 36):
        self.interpreter = SafetyConstraintInterpreter(
            safety=safety,
            max_delta_per_frame=max_delta_per_frame,
        )

    def __call__(self, state: PhotonicState) -> PhotonicState:
        start_time = time.time()
        strobe_budget = float(state["director_state"]["strobe_budget_hz"])
        state["fixture_commands"] = self.interpreter.interpret(
            state["fixture_commands"],
            strobe_budget_hz=strobe_budget,
        )
        state["processing_times"]["interpreter"] = time.time() - start_time
        return state
