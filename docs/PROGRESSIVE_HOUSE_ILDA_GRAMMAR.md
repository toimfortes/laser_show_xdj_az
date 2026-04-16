# Progressive House ILDA Grammar

This document defines the repo's normalized laser-show grammar for progressive house.

## Goals

- Treat the laser as a primary expressive fixture, not a generic effect.
- Separate `drop launch` from `drop sustain`.
- Use phrase-aware variation instead of repeating one look for an entire section.
- Prefer overhead / aerial looks by default until a real audience-scan safety workflow is commissioned.

## Core Families

- `beam`: groove-supporting beam looks such as fans, grouped sweeps, lattices, scans
- `abstract`: melodic or atmospheric looks such as helix, sky, cone, tunnel-like depth motion
- `transition`: handoff looks used in risers, cuts, launches, and phrase punctuation

## Section Rules

- `intro`
  - sparse beams
  - aerial or mid-air target bias
  - slow palette drift
  - no sustained shuttering

- `build`
  - tighten geometry every phrase
  - increase verticality and sweep pressure
  - use transition families late in the riser
  - save the hardest blanking for the handoff

- `drop`
  - use a short launch window with the highest intensity
  - normalize after the launch bars
  - rotate among multiple look classes during sustain
  - use strobes and white hits as punctuation, not constant occupancy

- `breakdown`
  - reduce beam density
  - favor abstracts and overhead looks
  - slow color morphs from harmonic content
  - minimal blanking

- `outro`
  - progressively subtract density
  - simplify to fans/scans
  - prepare a clean mix-out handoff

## Grammar Fields

Each generated `laser_expression` may carry:

- `content_family`
- `geometry_family`
- `target_strategy`
- `blanking_strategy`
- `color_strategy`
- `phrase_envelope`
- `transition_role`
- `variation_plan`

`phrase_envelope` includes:

- `launch_bars`
- `sustain_bars`
- `release_bars`
- `normalize_after_bars`
- `intensity_curve`
- `launch_intensity`
- `sustain_intensity`
- `release_intensity`
- `sustain_motion`

## Implementation Notes

- The planner currently generates these values from the Rekordbox segment structure and track seed.
- The ILDA output path should increasingly use these fields directly for frame generation.
- The DMX fallback path may use them as macro intent even when true ILDA output is unavailable.
