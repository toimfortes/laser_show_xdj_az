# Live Deck Auto-Bind Design

Date: 2026-04-20

## Goal

Bind lighting playback automatically to the correct song and the correct point in that song, using live DJ gear as the source of truth.

The normal production path must be fully automatic. Manual binding is allowed only as an explicit test mode.

## Problem

The current application can accept a manual `pro_dj_link` metadata payload through the web API and then bind `PlaybackContext` to that metadata. It does not yet own a real ingest path from DJ gear or a trustworthy binding engine.

The system needs two independent truths:

1. Track identity
2. Live transport position

If either truth is wrong, section binding is wrong. If both are ambiguous, the system must fail closed instead of guessing.

## Constraints

- The authoritative deck is always the deck that is both `on_air` and `master`.
- Production operation must not depend on manual browser actions.
- Manual binding is permitted only for testing and must be visually and behaviorally separate from live mode.
- Prefer supported or established bridge tooling before any direct PRO DJ LINK implementation.
- The design must allow a future direct-ingest adapter if no supported bridge can expose the needed data for XDJ-AZ.

## Research Summary

- XDJ-AZ can connect CDJs over PRO DJ LINK.
- CDJ-3000 firmware 3.16 added PRO DJ LINK connection support with XDJ-AZ.
- XDJ-AZ PRO DJ LINK mode has operational caveats:
  - deck 3 and 4 are disabled
  - built-in Wi-Fi use conflicts with PRO DJ LINK-compatible player connection
- AlphaTheta Stagehand support is documented for CDJ-3000 and DJM-A9, not XDJ-AZ.
- Official PRO DJ LINK Bridge and TC Supply products provide a bridge-oriented integration path, but currently documented supported-device lists do not clearly include XDJ-AZ.

This leaves one unresolved production question:

- Can a supported bridge expose authoritative `on_air`, `master`, track identity, and transport data in an XDJ-AZ plus CDJ-3000 setup?

The design below assumes the answer may be "not always," and isolates ingest behind a port so the application core does not care whether the source is TCNet or a future direct adapter.

## Recommended Architecture

### 1. LiveDeckIngestPort

Introduce a normalized ingest boundary that emits per-deck facts.

Required fields:

- `player_number`
- `track_title`
- `track_artist`
- `duration_seconds`
- `playhead_seconds`
- `bpm`
- `speed`
- `master`
- `on_air`
- `playing`
- `updated_at`

Optional fields when available:

- `track_id`
- `album`
- `artwork`
- `beat_phase`
- `cue_state`
- `source_type`

The rest of the app consumes only this normalized shape.

### 2. Ingest Adapters

#### TcnetIngestAdapter

Primary production adapter.

- Reads deck facts from a supported upstream bridge such as ShowKontrol, BeatKontrol, or PRO DJ LINK Bridge if they expose the necessary fields.
- Converts bridge payloads into `LiveDeckIngestPort` events.
- Does not contain authority or binding policy.

#### ManualTestIngestAdapter

Debug-only adapter.

- Enabled by a visible web toggle.
- Injects synthetic deck state into the same ingest port.
- Uses the same authority and binding engine as production ingest.
- Must never be active by accident.

#### Future DirectProDjLinkAdapter

Deferred fallback adapter.

- Only needed if supported bridge tooling cannot deliver authoritative XDJ-AZ data.
- Isolated behind the same ingest port to avoid contaminating core logic.

### 3. AutoBindEngine

Consumes normalized deck facts and drives binding state.

Responsibilities:

- elect authority deck
- resolve track identity
- determine active section from playhead
- publish explicit binding state
- update `PlaybackContext` only when binding is valid

## Binding Logic

### Authority Election

The election rule is strict:

- choose exactly one deck where `master == true` and `on_air == true`

Result states:

- no such deck: `unbound`
- more than one such deck: `conflict`
- one such deck: authority selected
- authority stops updating past freshness threshold: `stale`

No fallback to "currently playing" or "largest playhead advance" is allowed in production mode.

### Track Resolution

Track resolution converts authority-deck metadata into a local show identity.

Resolution order:

1. exact `title + artist + duration`
2. `title + artist` with duration tolerance
3. constrained fallback using combinations of title, artist, duration, and BPM only if confidence remains high

Rules:

- exact match wins
- multiple plausible matches produce `ambiguous`
- no silent best-guess behavior
- unknown track produces `unbound` or `unsupported_source`, depending on the reason

Resolution target sources:

- persisted show plans
- Rekordbox-derived track metadata
- any existing local track-key universe already used by the app

### Section Binding

Once a track is resolved:

- active section is determined strictly from the authority deck's `playhead_seconds`
- normal transport movement updates section position only
- full track re-resolution happens only when track identity changes or authority changes decks

## Binding States

Expose explicit machine states:

- `bound`
- `unbound`
- `ambiguous`
- `stale`
- `conflict`
- `unsupported_source`

Each state includes:

- `reason`
- `authority_player`
- `resolved_track_key`
- `match_confidence`
- `last_update_at`

## PlaybackContext Integration

`PlaybackContext` remains the UI-facing runtime state, but it is no longer the source of truth for authority selection.

Integration rules:

- valid auto-bind updates call the existing metadata binding path
- invalid or ambiguous states do not mutate authored track identity
- section position updates continue from authoritative live transport only when binding is valid
- stale or conflicting authority must not silently preserve a false "good" bound state forever

Fail-closed behavior:

- brief grace window after freshness loss
- after grace window, expose `stale` and stop rebinding authored state

## UI Design

### Live Status Panel

Show at-a-glance operational truth:

- `Bound to Deck N`
- `Master + On Air`
- resolved track title and artist
- current section label
- freshness readout such as `last update 120 ms ago`
- binding status badge

### Test Mode

Manual test mode must be unmistakable.

Requirements:

- explicit toggle labeled for testing only
- loud visual state such as `TEST MODE`
- production ingest is suspended while test mode is active
- same binding engine logic still applies

## Logging and Observability

Log the following events:

- authority deck change
- track resolution success
- track resolution rejection with reason
- transition into `stale`, `conflict`, `ambiguous`, or `unsupported_source`
- exit from test mode back to live mode

The UI should surface enough state for the operator to understand whether a problem is:

- ingest failure
- authority conflict
- track ambiguity
- missing local show identity

## Failure Modes

### No Authority Deck

- state: `unbound`
- behavior: do not change authored track binding

### Multiple Authority Decks

- state: `conflict`
- behavior: fail closed, do not switch tracks

### Authority Goes Stale

- state: `stale`
- behavior: hold briefly, then stop rebinding

### Ambiguous Track Match

- state: `ambiguous`
- behavior: do not switch authored plan

### Unsupported Bridge Source

- state: `unsupported_source`
- behavior: surface clear operator message that the upstream bridge does not provide sufficient data for trusted auto-binding

## Testing Strategy

### Unit Tests

- authority election with single valid deck
- no-authority case
- multi-authority conflict case
- stale-authority transition
- exact track resolution
- ambiguous track resolution
- section binding from live playhead
- test-mode ingest still flows through the same binding engine

### Integration Tests

- live deck A binds, deck B ignored
- authority handoff from deck A to deck B
- stale authority enters fail-closed state
- ambiguous metadata refuses authored track swap
- unsupported-source state surfaces without mutating live binding

## Scope Boundaries

Included in this design:

- ingest boundary
- authority election
- track resolution
- binding-state model
- UI status model
- test-mode toggle

Not included in this design:

- direct PRO DJ LINK protocol implementation
- browser song browsing
- replacing the current show-planning model
- speculative support for heuristics that override the `on_air && master` rule

## Recommendation

Implement a TCNet-first or bridge-first auto-bind pipeline behind `LiveDeckIngestPort`, with manual test input as a separate adapter and no production fallback heuristics beyond the explicit `on_air && master` rule.

If supported bridge tooling cannot expose authoritative XDJ-AZ state, only then introduce a direct PRO DJ LINK adapter as a contained fallback implementation.
