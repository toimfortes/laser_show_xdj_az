# Live Section Dynamics Wiring Design

## Summary

This design makes the highest-value dead controls in the section editor affect live output immediately during playback.

The slice is intentionally narrow:

- wire `intensity_multiplier`
- wire `motion_multiplier`
- wire `strobe_level`
- wire `laser_enabled`
- wire `movers_enabled`
- wire `washes_enabled`
- wire `leds_enabled`

These values already exist in authored `show_sections` and already round-trip through the web panel and `PlaybackContext`. The missing link is runtime consumption inside the graph nodes that actually emit DMX and ILDA output.

## Goals

- Make existing section-editor controls change real live output without requiring regeneration
- Preserve the current authored show-plan structure and web API shape
- Keep safety interlocks authoritative
- Keep the first slice local to runtime consumers instead of reworking show planning

## Non-Goals

- Full section-editor parity in one pass
- Rewiring `scene_id`, `fixture_mode`, or the family pattern selectors
- Introducing a new runtime override subsystem
- Changing control-plane command semantics
- Changing the preview canvas / mock rig behavior in this slice

## Why This Slice First

These controls are the highest-value dead fields because they are direct performance controls:

- `intensity_multiplier` is the most obvious “make this section hit harder / softer” control
- `motion_multiplier` is the most obvious “make this section move more / less” control
- `strobe_level` is a live energy control that operators expect to matter immediately
- family enable flags are explicit hard gates and should never be decorative

They also fit the current runtime architecture well:

- the active section is already available via `playback_snapshot`
- `fixture_control` and `ilda_output` already resolve the active section each tick
- the change can be implemented as runtime modifiers instead of authored-plan regeneration

## Current Problem

The current section editor persists these fields, but the live tick mostly ignores them.

Today, the runtime path is dominated by:

- control-plane state for global live controls
- director state for palette / structure / motion policy
- `laser_program` and selected laser looks for phrase-window behavior

As a result:

- section edits to `intensity_multiplier`, `motion_multiplier`, and `strobe_level` are mostly inert
- `laser_enabled` is also effectively inert at runtime because the live laser path keys off `laser_program`
- mover / wash / LED family flags are not used as hard gates in the family emitters

## Design

### 1. Add one shared resolver for active section dynamics

Add a small helper in the graph/runtime layer that:

- reads `playback_snapshot`
- resolves the active section by `playhead_seconds`
- returns a normalized dynamics payload:
  - `intensity_multiplier: float`
  - `motion_multiplier: float`
  - `strobe_level: float`
  - `laser_enabled: bool`
  - `movers_enabled: bool`
  - `washes_enabled: bool`
  - `leds_enabled: bool`

Normalization rules:

- missing numeric fields fall back to `1.0` for intensity/motion and `0.0` for strobe
- missing booleans fall back to `True` for family enables
- the helper is total: invalid/malformed values degrade to defaults instead of raising

This helper must be reusable by multiple runtime nodes so the enable/dynamics rules stay consistent.

### 2. Apply family enable flags as hard gates

Add hard gating in the family-specific runtime emitters:

- `LaserControlNode` and `ILDAOutputNode` honor `laser_enabled`
- `MovingHeadControlNode` honors `movers_enabled`
- `PanelControlNode` honors:
  - `washes_enabled` for wash fixtures
  - `leds_enabled` for panel/LED fixtures as appropriate

Behavior:

- when a family is disabled for the active section, that family emits no live command/frame content for that section
- for DMX-driven families, "no live output" means the runtime must actively drive mapped channels to a safe neutral/off state if silence would otherwise leave the previous universe latched
- this is stronger and clearer than merely scaling intensity to zero
- safety remains downstream and unchanged

`laser_enabled` needs special attention because there are two laser paths:

- DMX laser command generation in `LaserControlNode`
- ILDA frame generation in `ILDAOutputNode`

Both must honor the same active-section flag or the UI remains misleading. On the DMX side, honoring the flag must clear the mapped laser channels rather than relying on command omission, because the downstream DMX universe is stateful.

### 3. Apply intensity and motion as runtime modifiers

These multipliers should modify per-section output, not trigger plan regeneration.

#### `intensity_multiplier`

Apply as a late local scalar inside the family emitters:

- laser brightness / dimmer-like outputs
- moving-head dimmer and color/intensity-related values
- wash/panel dimmer outputs
- ILDA color amplitude / brightness-relevant outputs

Rules:

- multiply the family-local baseline by `intensity_multiplier`
- clamp to existing valid channel/range bounds
- do not bypass the global control-panel intensity scalar
- final effective output remains:
  - section intensity multiplier
  - then global intensity
  - then interpreter/safety clamping

#### `motion_multiplier`

Apply to the family-local movement clocks and motion amplitudes:

- scan/sweep speed
- pan/tilt motion rate or excursion
- animation phase advance
- ILDA geometric motion rate / modulation amount

Rules:

- scale local motion parameters, not wall-clock time globally
- keep any existing hard safety minima/maxima authoritative
- if a family has no motion axis for a given look, the multiplier is a no-op there

### 4. Apply strobe level as a runtime strobe bias

`strobe_level` should affect live strobe aggressiveness, but it must remain subordinate to existing safety logic.

Implementation rule:

- convert `strobe_level` into a section-local strobe scalar in the family emitters
- use that scalar to reduce or increase emitted strobe-like values and accent intensity
- the safety interpreter and strobe budget remain the final authority

Practical effect:

- `strobe_level = 0` means the section should emit no intentional strobe behavior
- higher values increase family-local strobe intent
- safety can still suppress or cap that output

This is explicitly not a new direct hardware strobe bypass.

### 5. Keep deferred fields deferred

The following fields are intentionally deferred to a later slice:

- `scene_id`
- `fixture_mode`
- `laser_pattern`
- `mover_pattern`
- `wash_pattern`
- `led_pattern`

Reason:

- these are not simple runtime scalars
- they overlap with authored-plan generation, scene selection policy, and pattern-program construction
- forcing them into this slice would widen the change from “make dead performance controls live” into “re-architect section authorship semantics”

## File-Level Impact

Expected primary touch points:

- `src/photonic_synesthesia/graph/nodes/fixture_control.py`
- `src/photonic_synesthesia/graph/nodes/ilda_output.py`

Expected new helper location:

- a small runtime helper module near graph/runtime consumers, or a tightly-scoped helper inside an existing graph node module if reuse remains clean

Likely no changes required to:

- web endpoints
- `PlaybackContext` persistence contract
- control-plane command bus

## Safety Constraints

This slice must preserve the current authority chain:

1. authored section dynamics shape local family intent
2. control-plane global intensity still applies
3. interpreter and safety interlock still clamp/cap output
4. laser vector/runtime safety remains unchanged

No section-editor field may create a path that bypasses:

- global blackout
- armed/disarmed gating
- strobe limits
- laser safety limits

## Testing Strategy

Add focused unit tests that prove live consumption, not just persistence.

### Required tests

- section `intensity_multiplier` changes produce different emitted commands/frames for the active section
- section `motion_multiplier` changes alter motion-driving values for the active section
- section `strobe_level = 0` suppresses intentional strobe behavior
- family enable flags suppress their family output:
  - `laser_enabled = false`
  - `movers_enabled = false`
  - `washes_enabled = false`
  - `leds_enabled = false`
- DMX laser disable clears the mapped laser channels in the live universe instead of leaving the prior look latched
- disabled family in one section does not suppress output in neighboring enabled sections
- ILDA and DMX laser paths both honor `laser_enabled`

### Regression checks

- global control-panel intensity still works on top of section intensity
- blackout / arm/disarm behavior is unchanged
- no changes to mock-rig-only endpoints

## Success Criteria

This slice is complete when:

- moving the section-editor sliders for intensity, motion, and strobe changes real live output
- toggling family enable checkboxes changes real live output for the active section
- `laser_enabled` affects both DMX-laser and ILDA-laser paths consistently
- DMX-laser disable actively neutralizes mapped channels so the prior look does not remain latched in the universe
- deferred fields remain explicitly documented as deferred and unchanged
- tests prove live behavior changes in runtime consumers

## Follow-On Slice

After this lands, the next highest-value slice is:

- either wire `scene_id` / `fixture_mode` / pattern-family fields into runtime behavior
- or relabel / partition the remaining dead editor controls so the UI stops overstating what is live

That follow-on should be planned separately because it touches authored-plan semantics rather than just runtime consumption.
