# Section Runtime Overrides Design

## Summary

This design closes the next highest-value live-wiring gaps in authored
`show_sections` by making these fields affect runtime behavior:

- `scene_id`
- `section_mode` (hard rename from `fixture_mode`)
- `laser_pattern`
- `mover_pattern`
- `wash_pattern`
- `led_pattern`

The slice keeps the same high-level principle as the previous live
section-dynamics work:

- the active authored section should shape live output by default
- explicit live operator controls still win
- safety, blackout, arming, and global masters remain authoritative

## Goals

- Make authored `scene_id` drive live scene selection by default during playback
- Make authored family pattern fields change live runtime behavior for the active section
- Replace the misleading `fixture_mode` name with the standard-aligned `section_mode`
- Keep runtime behavior layered on top of the current graph instead of replacing the planner/director architecture
- Preserve operator override paths and safety behavior

## Non-Goals

- Introducing a new runtime override subsystem
- Adding fixture-specific hardware personality/mode switching
- Reworking the preview canvas / mock rig semantics outside the required field rename
- Preserving backward compatibility for `fixture_mode`
- Replacing `laser_program` phrase-window timing or scene JSON structure

## Key Decisions

### 1. `scene_id` becomes the default live scene target

The active section's `scene_id` should drive scene selection in
`SceneSelectNode` by default.

Priority order:

1. `scene_hold`
2. `launched_scene`
3. active section `scene_id`
4. director target scene
5. structure fallback

This gives authored sections real live effect while preserving operator
authority. It is explicitly not a hard lock: manual hold/launch must
still override the authored section.

### 2. Pattern fields become direct family overrides

The active section's family pattern fields should directly control the
family-specific runtime selector for the active section:

- `laser_pattern`
- `mover_pattern`
- `wash_pattern`
- `led_pattern`

The intended behavior is narrow and explicit:

- pattern fields override family/pattern selection
- they do not replace the entire look object
- they do not bypass safety, blackout, arming, or global controls
- they should compose with existing timing/role logic instead of deleting it

That means:

- `laser_pattern` overrides rendered laser family selection for both DMX
  laser output and ILDA output
- `mover_pattern` overrides mover motion-family selection and associated
  gobo behavior
- `wash_pattern` and `led_pattern` override panel-family render mode
  selection for the current active section

### 3. Hard rename `fixture_mode` to `section_mode`

`fixture_mode` is not standard terminology for the current data shape.
The authored values (`peak_return`, `rebuild`, `breakdown`, `intro`,
`outro`) are section behavior presets, not hardware fixture
personalities.

The field is therefore hard-renamed repo-wide:

- old field: `fixture_mode`
- new canonical field: `section_mode`

This slice intentionally does not keep a compatibility alias. All
repo-owned producers, consumers, tests, and UI surfaces should be
updated in one pass.

### 4. `section_mode` is a cross-family behavior preset

`section_mode` should shape shared live behavior, not low-level fixture
hardware mode channels.

It should bias:

- motion posture
- section/drop/build envelope
- accent/strobe appetite
- emphasis level across families

It should not:

- directly map to manufacturer-specific DMX operating modes
- alter fixture profile/channel-footprint selection
- become a second copy of the pattern fields

The mapping must stay small and explicit. Initial supported presets:

- `intro`
- `breakdown`
- `rebuild`
- `peak_return`
- `outro`

Expected semantic intent:

- `intro`: restrained motion, restrained strobe, calmer envelope
- `breakdown`: sparse motion, lower strobe appetite, atmospheric emphasis
- `rebuild`: rising motion posture, increasing lift/tension emphasis
- `peak_return`: aggressive return/drop-like envelope, stronger accents
- `outro`: fade/settle behavior, lower intensity and motion appetite

## Runtime Design

### Shared active-section contract

Extend the shared active-section runtime helper so it returns normalized
values for:

- `scene_id`
- `section_mode`
- `laser_pattern`
- `mover_pattern`
- `wash_pattern`
- `led_pattern`

This keeps the active section as the single source of truth for authored
runtime overrides.

Normalization rules:

- missing `scene_id` resolves to `None`
- missing `section_mode` resolves to `""`
- missing pattern fields resolve to `""`
- malformed values degrade to empty strings rather than raising

### Scene selection

`SceneSelectNode` should use active-section `scene_id` only when:

- no scene hold is active
- no launched scene is pending

Validation rules:

- if the active section `scene_id` is not present in the scene catalog,
  log/debug it and continue to the director/structure fallback path
- scene transitions still use existing transition timing and rules

This preserves the current authority chain while making section-authored
scene changes live.

### Laser family behavior

#### DMX laser path

`LaserControlNode` should interpret active `laser_pattern` as the live
pattern override for the current section.

It should:

- map authored laser patterns into DMX pattern-selection behavior
- continue using section/global motion scalars and safety clamps
- continue clearing mapped channels when lasers are disabled

#### ILDA laser path

`ILDAOutputNode` should interpret active `laser_pattern` as the geometry
family override for the current section.

It should:

- preserve the existing phrase-window timing and role selection from
  `laser_program`
- replace only the rendered geometry family when an authored pattern is
  present
- keep color/target/strobe behavior flowing through the current runtime
  logic unless separately authored elsewhere

This avoids wiping out useful phrase timing while still making the
section editor's pattern field visibly live.

### Moving-head behavior

`MovingHeadControlNode` should treat active `mover_pattern` as the live
motion-family override for the current section.

It should:

- map authored patterns into mover families such as hold/hits/cross/
  rise/shape
- let the existing motion/intensity/strobe scalars continue shaping the
  emitted values
- keep gobo selection coupled to the resolved mover family

### Panel behavior

`PanelControlNode` currently represents both wash-like and LED-like
family output. The active section should therefore route patterns
explicitly:

- wash-side panel behavior follows `wash_pattern`
- LED-side panel behavior follows `led_pattern`

`section_mode` should then bias the shared envelope on top of that
family-specific pattern choice.

This is important because otherwise wash and LED pattern fields collapse
back into one ambiguous implementation.

## File-Level Impact

Expected primary touch points:

- `src/photonic_synesthesia/graph/nodes/section_dynamics.py`
- `src/photonic_synesthesia/graph/nodes/scene_select.py`
- `src/photonic_synesthesia/graph/nodes/fixture_control.py`
- `src/photonic_synesthesia/graph/nodes/ilda_output.py`
- `src/photonic_synesthesia/platform/runtime_context.py`
- `src/photonic_synesthesia/showplan/sections.py`
- `src/photonic_synesthesia/showplan/cue_recipe.py`
- `src/photonic_synesthesia/showplan/model_payloads.py`
- `src/photonic_synesthesia/showplan/validation.py`
- `src/photonic_synesthesia/ui/web_panel.py`
- `src/photonic_synesthesia/ui/static/mock_control_plane.js`

Expected test touch points:

- `tests/unit/test_scene_select.py`
- `tests/unit/test_runtime_nodes.py`
- `tests/unit/test_fixture_control.py`
- `tests/unit/test_ilda_output.py`
- `tests/unit/test_runtime_context_helpers.py`
- `tests/unit/test_web_panel.py`
- `tests/unit/test_production_hardening.py`
- planner tests that assert authored field names/contents

## Migration and Contract Impact

This is a deliberate breaking rename inside the repo-owned contract.

After this slice:

- `section_mode` is the only supported field name
- `fixture_mode` is removed from planner/runtime/UI/test expectations

Consequences:

- in-repo snapshots, API payloads, UI forms, and tests should all use
  `section_mode`
- persisted external payloads using `fixture_mode` are out of contract
  after this change unless separately migrated

## Safety and Control Constraints

No authored section field in this slice may bypass:

- blackout
- armed/disarmed gating
- existing DMX/ILDA safety logic
- global intensity/speed controls
- current strobe/safety clamps

The intended authority chain remains:

1. operator hold/launch overrides for scene choice
2. active authored section overrides by default
3. director/structure fallback behavior
4. global masters and safety layers

## Testing Strategy

Add focused tests that prove live effect rather than metadata presence.

### Required coverage

- active section `scene_id` drives scene selection when no manual
  hold/launch is active
- manual hold/launch still overrides section `scene_id`
- invalid authored `scene_id` falls back safely
- `laser_pattern` changes both DMX laser output and ILDA geometry
  selection
- `mover_pattern` changes live mover family behavior
- `wash_pattern` and `led_pattern` change live panel-family behavior
- `section_mode` changes live shared emphasis/envelope behavior
- no remaining repo-owned runtime/editor/planner payloads expose
  `fixture_mode`

### Regression checks

- previous live section-dynamics behavior remains intact
- laser disable still clears latched DMX output
- blackout / arm/disarm behavior is unchanged
- scene transition timing logic is unchanged except for the new authored
  source of target scene

## Risks

### 1. Hard rename breakage

The rename is cleanest architecturally, but it is a deliberate contract
break. Missing one producer/consumer/test path will create inconsistent
payloads quickly.

### 2. Overriding too much

Pattern fields should stay narrow. If implementation replaces complete
look objects instead of just family selection, it can erase useful
phrase-window behavior and over-couple section editing to low-level
runtime internals.

### 3. `section_mode` becoming a junk drawer

`section_mode` must stay a small preset layer. If it starts controlling
too many unrelated knobs directly, it becomes ambiguous and hard to
reason about.

### 4. Scene churn on short sections

Very short adjacent sections with different `scene_id`s may request
rapid target changes. Existing scene transition logic should still own
that behavior, but it needs explicit tests.

## Success Criteria

This slice is complete when:

- authored `scene_id` changes live scene selection by default
- authored family pattern fields change real live output for the active
  section
- `fixture_mode` has been replaced repo-wide by `section_mode`
- `section_mode` has a clear, limited runtime meaning as a section
  behavior preset
- operator authority and safety behavior remain intact
- tests prove live runtime effect and the rename is complete
