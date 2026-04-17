# Control Plane Website Plan

Date: 2026-04-15
Status: Planning
Scope: Build a first-class operator and authoring website for Photonic Synesthesia, inspired by Force-style workflows but grounded in typed platform commands and event streams.

## 0. Executive Summary

The website should be a control plane, not a thin dashboard and not a direct runtime editor.

It must support:
- live operation
- safety visibility and intervention
- patching and diagnostics
- replay and preview
- scene and bank authoring
- controlled multi-user access

This document defines the website architecture, API surface, session model, screen set, and phased rollout.

## 1. Goals

1. Provide a real operator surface for live show control.
2. Support scalable multi-fixture and multi-universe systems.
3. Respect platform contracts by issuing typed commands only.
4. Expose replay and preview as first-class workflows.
5. Support future scene authoring and ML-assisted tooling without redesigning the site.

## 2. Non-Goals For V1

1. No direct raw DMX editing as the primary workflow.
2. No unconstrained mutation of scene internals from the browser.
3. No assumption that one operator is the only connected client.
4. No hardwiring of the site to current single-laser semantics.

## 3. Product Model

The website has four roles:
- Observer
- Operator
- Programmer
- Admin

Role intent:
- Observer can view live state and replay.
- Operator can issue live control commands.
- Programmer can edit scenes, banks, and patch definitions.
- Admin can manage authority, sessions, and transport configuration.

## 4. Control Authority Model

The system must enforce operator authority explicitly.

### 4.1 Session Types

- observer session
- control session
- programming session

### 4.2 Control Lease

Rules:
- only one control lease is active at a time
- lease owner can issue mutating live commands
- observers can watch but not mutate
- admin can revoke or transfer lease
- programming actions are blocked or sandboxed while live control is armed

### 4.3 Required Website States

- disconnected
- connected_observer
- connected_controller
- connected_programmer
- replay_mode
- armed_live
- safe_hold
- blackout_active

## 5. Backend Architecture

Use FastAPI because it already matches the repo dependency direction and supports:
- lifespan-managed startup
- REST APIs
- WebSockets
- static asset serving

Proposed backend modules:
- `src/photonic_synesthesia/ui/web_panel.py`
- `src/photonic_synesthesia/ui/api/live.py`
- `src/photonic_synesthesia/ui/api/control.py`
- `src/photonic_synesthesia/ui/api/patch.py`
- `src/photonic_synesthesia/ui/api/scenes.py`
- `src/photonic_synesthesia/ui/api/replay.py`
- `src/photonic_synesthesia/ui/ws/live.py`
- `src/photonic_synesthesia/ui/auth/authority.py`

## 6. API Model

### 6.1 Read APIs

- `GET /api/live/state`
- `GET /api/live/health`
- `GET /api/live/safety`
- `GET /api/live/director`
- `GET /api/live/patch`
- `GET /api/live/universes`
- `GET /api/live/fixtures`
- `GET /api/replay/catalog`
- `GET /api/replay/{replay_id}`
- `GET /api/scenes`
- `GET /api/scenes/{scene_id}`

### 6.2 Write APIs

All writes map to `OperatorCommand` or programming commands.

- `POST /api/control/lease/acquire`
- `POST /api/control/lease/release`
- `POST /api/control/blackout`
- `POST /api/control/clear-blackout`
- `POST /api/control/arm`
- `POST /api/control/disarm`
- `POST /api/control/intensity`
- `POST /api/control/speed`
- `POST /api/control/auto-mode`
- `POST /api/control/scenes/launch`
- `POST /api/control/scenes/hold`
- `POST /api/control/scenes/release`
- `POST /api/control/groups/override`
- `POST /api/control/palette/override`
- `POST /api/control/transports/state`
- `POST /api/replay/start`
- `POST /api/replay/stop`
- `POST /api/program/scenes`
- `POST /api/program/scenes/{scene_id}/compile`
- `POST /api/program/patch`

### 6.3 WebSocket Channels

- `/ws/live`
- `/ws/safety`
- `/ws/replay`
- `/ws/diagnostics`

Broadcast payloads:
- live snapshot
- platform events
- safety events
- transport health
- replay position

## 7. Frontend Screens

### 7.1 V1 Screens

#### Run

Primary information:
- transport and armed state
- active scene and pending scene
- beat/downbeat and structure
- director intent
- global intensity and speed
- control lease owner

Primary controls:
- arm/disarm
- blackout/clear blackout
- global intensity
- global speed
- auto/hold mode
- launch selected scene

#### Safety

Primary information:
- heartbeat state
- safety interlock status
- active cooldowns
- watchdog health
- transport faults

Primary controls:
- blackout
- safe hold
- clear noncritical faults

#### Overrides

Primary information:
- active fixture-group overrides
- palette override
- scene hold state

Primary controls:
- group intensity override
- group enable/disable
- palette override
- override clear

#### Patch

Primary information:
- fixture inventory
- fixture capabilities
- group membership
- universe placement
- transport routing

Primary controls:
- patch edit in programming mode
- fixture enable/disable
- universe assignment

#### Universe Monitor

Primary information:
- universe list
- slot occupancy
- fixture-oriented view
- transport status per universe

Primary controls:
- monitoring only in V1

#### Replay

Primary information:
- replay catalog
- timeline position
- event markers
- active scene and safety events at position

Primary controls:
- play
- pause
- scrub
- speed adjust

### 7.2 V2 Screens

- Scene Builder
- Attribute Banks
- Quick Load
- Transition Editor
- Trigger Sequencer
- Preview Renderer
- Diagnostics Deep Dive

## 8. UX Principles

1. The Run screen must remain operable under stress.
2. The site must degrade gracefully on mobile and desktop.
3. Safety controls remain visible at all times in live mode.
4. Programming workflows must not clutter live operations.
5. Status freshness must be obvious.

## 9. Data Flow

### 9.1 Live Command Flow

1. user issues UI action
2. UI sends API request
3. backend validates authority
4. backend emits typed command to command bus
5. runtime accepts or rejects command
6. backend publishes resulting event and updated snapshot
7. all subscribed clients receive update

### 9.2 Replay Flow

1. user selects replay
2. backend mounts replay session
3. replay engine publishes snapshots and events over replay channel
4. UI renders live-like state using replay frames

## 10. Security And Reliability

Required controls:
- session identity
- control lease enforcement
- write audit trail
- CSRF/session protections for browser flows
- rate limiting on mutating endpoints
- idempotent command handling where possible

Operational expectations:
- site stays usable if one telemetry stream fails
- observers do not block operators
- stale control sessions expire cleanly

## 11. Technical Implementation Plan

### Phase 1: Service Skeleton

Deliverables:
- FastAPI app
- lifespan hooks
- static asset mount
- websocket manager
- health endpoint

Acceptance:
- `photonic-web` starts and serves status page

### Phase 2: Control Plane V1

Deliverables:
- control lease model
- live read APIs
- core write APIs
- Run, Safety, Overrides, Patch, Universe Monitor, Replay screens

Acceptance:
- one controller plus multiple observers work concurrently

### Phase 3: Programming Surfaces

Deliverables:
- scene CRUD
- patch CRUD
- compile actions
- scene list and patch editor UIs

Acceptance:
- authored updates move through typed programming endpoints

### Phase 4: Advanced Authoring

Deliverables:
- Scene Builder
- Attribute Banks
- Quick Load
- Trigger Sequencer
- Preview Renderer

Acceptance:
- scenes can be built, previewed, and compiled from the website

## 12. Acceptance Metrics

Control metrics:
- command acknowledgment latency
- websocket freshness
- lease handoff latency

UI metrics:
- page load time
- control round-trip latency
- replay scrub responsiveness

Reliability metrics:
- concurrent client count supported
- reconnect success rate
- websocket drop recovery time

## 13. Reference Fit

This site should be comparable in sophistication to dedicated show-control surfaces, including Force-style run, bank, override, and fixture views, but its backend semantics must be grounded in the platform contracts defined in `docs/SCALABLE_PLATFORM_PLAN.md`.

## 14. References

- Force 1.0 manual: <https://static1.squarespace.com/static/65f8c22419f3b248b0b290f4/t/671beeeee86b732ff32448db/1729883889127/Force_1p0_rev1.pdf>
- FastAPI events docs: <https://fastapi.tiangolo.com/advanced/events/>
- FastAPI WebSockets docs: <https://fastapi.tiangolo.com/advanced/websockets/>
- FastAPI static files docs: <https://fastapi.tiangolo.com/tutorial/static-files/>
- DigiShow repository: <https://github.com/robinz-labs/digishow>
