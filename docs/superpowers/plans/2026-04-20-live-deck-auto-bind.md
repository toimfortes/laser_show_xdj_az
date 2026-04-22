# Live Deck Auto-Bind Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a supported-bridge-first live deck auto-bind pipeline that binds the show to the authoritative `on_air && master` deck, resolves the correct track, updates section position from live playhead, and keeps manual binding available only as an explicit test mode.

**Architecture:** Add a normalized live-deck ingest boundary plus a small auto-bind engine in the platform layer. Keep production ingest pluggable, starting with a TCNet-facing adapter boundary and a manual-test adapter, then integrate the binding result into `PlaybackContext` and the web panel without changing the existing authored showplan model.

**Tech Stack:** Python 3, FastAPI, Pydantic settings/models, existing `PlaybackContext` runtime services, frontend JavaScript in `mock_control_plane.js`, pytest.

---

## File Structure

### New files

- `src/photonic_synesthesia/platform/live_deck_models.py`
  - Pydantic/dataclass definitions for normalized deck facts and binding state.
- `src/photonic_synesthesia/platform/live_deck_binding.py`
  - Authority election, freshness checks, track resolution orchestration, binding-state transitions.
- `src/photonic_synesthesia/platform/live_deck_ingest.py`
  - Ingest port/protocol plus manual-test adapter scaffolding and a stub TCNet adapter boundary.
- `tests/unit/test_live_deck_binding.py`
  - Unit tests for authority election, stale/conflict/ambiguous states, and section binding decisions.
- `tests/unit/test_live_deck_ingest.py`
  - Unit tests for ingest state publication, manual test-mode behavior, and normalization boundaries.

### Modified files

- `src/photonic_synesthesia/core/config.py`
  - Extend `ProDJLinkConfig` with explicit ingest mode and freshness thresholds.
- `src/photonic_synesthesia/platform/runtime_context.py`
  - Add a controlled auto-bind entrypoint that applies resolved live binding into `PlaybackContext`.
- `src/photonic_synesthesia/platform/__init__.py`
  - Export new live-deck types/services.
- `src/photonic_synesthesia/ui/web_panel.py`
  - Add live-binding status endpoints and test-mode endpoints.
- `src/photonic_synesthesia/ui/static/mock_control_plane.js`
  - Render live binding state and test mode separately from normal playback controls.
- `tests/unit/test_web_panel.py`
  - Endpoint coverage for live-binding status and manual test input mode.
- `tests/unit/test_runtime_control_plane_integration.py`
  - Integration coverage of `PlaybackContext` plus live bind application.

## Task 1: Define Normalized Deck Facts and Binding State

**Files:**
- Create: `src/photonic_synesthesia/platform/live_deck_models.py`
- Modify: `src/photonic_synesthesia/platform/__init__.py`
- Test: `tests/unit/test_live_deck_binding.py`

- [ ] **Step 1: Write the failing test**

```python
from photonic_synesthesia.platform.live_deck_models import (
    BindingStatus,
    LiveDeckFact,
    LiveDeckSnapshot,
)


def test_live_deck_fact_normalizes_core_fields() -> None:
    fact = LiveDeckFact(
        player_number=3,
        track_title="Age of Love",
        track_artist="ARTBAT / Pete Tong",
        duration_seconds=445.4,
        playhead_seconds=183.2,
        bpm=128.0,
        speed=1.0,
        master=True,
        on_air=True,
        playing=True,
        updated_at=1713660000.0,
    )

    assert fact.player_number == 3
    assert fact.track_title == "Age of Love"
    assert fact.master is True
    assert fact.on_air is True


def test_binding_status_exposes_reason_and_confidence() -> None:
    status = BindingStatus(
        state="bound",
        reason="authoritative deck resolved",
        authority_player=3,
        resolved_track_key="ARTBAT|Age of Love",
        match_confidence=1.0,
        last_update_at=1713660000.0,
    )

    assert status.state == "bound"
    assert status.authority_player == 3
    assert status.match_confidence == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_live_deck_binding.py -k "live_deck_fact or binding_status" -v`

Expected: FAIL with `ModuleNotFoundError` or import failure for `live_deck_models`.

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class LiveDeckFact:
    player_number: int
    track_title: str = ""
    track_artist: str = ""
    duration_seconds: float = 0.0
    playhead_seconds: float = 0.0
    bpm: float = 0.0
    speed: float = 1.0
    master: bool = False
    on_air: bool = False
    playing: bool = False
    updated_at: float = 0.0
    track_id: str = ""
    source_type: str = ""


@dataclass(slots=True)
class LiveDeckSnapshot:
    decks: list[LiveDeckFact] = field(default_factory=list)


@dataclass(slots=True)
class BindingStatus:
    state: str
    reason: str
    authority_player: int | None = None
    resolved_track_key: str = ""
    match_confidence: float = 0.0
    last_update_at: float = 0.0
```

And export them in `src/photonic_synesthesia/platform/__init__.py`:

```python
from photonic_synesthesia.platform.live_deck_models import (
    BindingStatus,
    LiveDeckFact,
    LiveDeckSnapshot,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_live_deck_binding.py -k "live_deck_fact or binding_status" -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/photonic_synesthesia/platform/live_deck_models.py src/photonic_synesthesia/platform/__init__.py tests/unit/test_live_deck_binding.py
git commit -m "feat: add normalized live deck models"
```

## Task 2: Implement Authority Election and Binding State Engine

**Files:**
- Create: `src/photonic_synesthesia/platform/live_deck_binding.py`
- Test: `tests/unit/test_live_deck_binding.py`

- [ ] **Step 1: Write the failing test**

```python
from photonic_synesthesia.platform.live_deck_binding import LiveDeckAutoBindEngine
from photonic_synesthesia.platform.live_deck_models import LiveDeckFact


def test_engine_selects_single_on_air_master_deck() -> None:
    engine = LiveDeckAutoBindEngine(stale_after_seconds=0.5)
    status = engine.evaluate(
        [
            LiveDeckFact(player_number=1, playing=True, on_air=False, master=False, updated_at=100.0),
            LiveDeckFact(player_number=3, playing=True, on_air=True, master=True, updated_at=100.0),
        ],
        now=100.1,
    )

    assert status.state == "bound"
    assert status.authority_player == 3


def test_engine_reports_conflict_for_multiple_on_air_master_decks() -> None:
    engine = LiveDeckAutoBindEngine(stale_after_seconds=0.5)
    status = engine.evaluate(
        [
            LiveDeckFact(player_number=1, on_air=True, master=True, updated_at=100.0),
            LiveDeckFact(player_number=2, on_air=True, master=True, updated_at=100.0),
        ],
        now=100.1,
    )

    assert status.state == "conflict"
    assert status.authority_player is None


def test_engine_reports_stale_when_last_authority_expires() -> None:
    engine = LiveDeckAutoBindEngine(stale_after_seconds=0.5)
    engine.evaluate(
        [LiveDeckFact(player_number=3, on_air=True, master=True, updated_at=100.0)],
        now=100.1,
    )
    status = engine.evaluate([], now=100.8)

    assert status.state == "stale"
    assert status.authority_player == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_live_deck_binding.py -k "engine_" -v`

Expected: FAIL with import failure for `LiveDeckAutoBindEngine`.

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

from dataclasses import dataclass

from photonic_synesthesia.platform.live_deck_models import BindingStatus, LiveDeckFact


@dataclass(slots=True)
class LiveDeckAutoBindEngine:
    stale_after_seconds: float = 0.5
    _last_authority_player: int | None = None
    _last_authority_at: float = 0.0

    def evaluate(self, decks: list[LiveDeckFact], *, now: float) -> BindingStatus:
        authoritative = [deck for deck in decks if deck.on_air and deck.master]
        if len(authoritative) > 1:
            return BindingStatus(
                state="conflict",
                reason="multiple on-air master decks",
                authority_player=None,
                last_update_at=now,
            )
        if len(authoritative) == 1:
            deck = authoritative[0]
            self._last_authority_player = deck.player_number
            self._last_authority_at = float(deck.updated_at or now)
            return BindingStatus(
                state="bound",
                reason="authoritative deck resolved",
                authority_player=deck.player_number,
                last_update_at=float(deck.updated_at or now),
            )
        if self._last_authority_player is not None and now - self._last_authority_at >= self.stale_after_seconds:
            return BindingStatus(
                state="stale",
                reason="authoritative deck timed out",
                authority_player=self._last_authority_player,
                last_update_at=self._last_authority_at,
            )
        return BindingStatus(
            state="unbound",
            reason="no on-air master deck",
            authority_player=None,
            last_update_at=now,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_live_deck_binding.py -k "engine_" -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/photonic_synesthesia/platform/live_deck_binding.py tests/unit/test_live_deck_binding.py
git commit -m "feat: add live deck authority engine"
```

## Task 3: Add Track Resolution and PlaybackContext Auto-Bind Entry Point

**Files:**
- Modify: `src/photonic_synesthesia/platform/live_deck_binding.py`
- Modify: `src/photonic_synesthesia/platform/runtime_context.py`
- Test: `tests/unit/test_live_deck_binding.py`
- Test: `tests/unit/test_runtime_control_plane_integration.py`

- [ ] **Step 1: Write the failing test**

```python
from photonic_synesthesia.platform import PlaybackContext
from photonic_synesthesia.platform.live_deck_binding import resolve_track_identity


def test_resolve_track_identity_prefers_exact_title_artist_duration() -> None:
    payload = resolve_track_identity(
        title="Age of Love",
        artist="ARTBAT / Pete Tong",
        duration_seconds=445.4,
        candidates=[
            {"track_key": "ARTBAT / Pete Tong|Age of Love", "track_title": "Age of Love", "track_artist": "ARTBAT / Pete Tong", "duration_seconds": 445.4},
            {"track_key": "Another Artist|Age of Love", "track_title": "Age of Love", "track_artist": "Another Artist", "duration_seconds": 445.4},
        ],
    )

    assert payload["state"] == "bound"
    assert payload["resolved_track_key"] == "ARTBAT / Pete Tong|Age of Love"


def test_playback_context_apply_live_binding_updates_transport_and_track() -> None:
    ctx = PlaybackContext(file_path="", file_name="Live Track", duration_seconds=0.0, track_title="Live Track")
    snapshot = ctx.apply_live_binding(
        {
            "state": "bound",
            "resolved_track_key": "ARTBAT / Pete Tong|Age of Love",
            "track_title": "Age of Love",
            "track_artist": "ARTBAT / Pete Tong",
            "duration_seconds": 445.4,
            "playhead_seconds": 183.2,
            "metadata_source": "pro_dj_link",
        }
    )

    assert snapshot["track_title"] == "Age of Love"
    assert snapshot["playhead_seconds"] == 183.2
    assert snapshot["metadata_source"] == "pro_dj_link"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_live_deck_binding.py -k "resolve_track_identity" -v && pytest tests/unit/test_runtime_control_plane_integration.py -k "apply_live_binding" -v`

Expected: FAIL with missing resolver function and missing `PlaybackContext.apply_live_binding`.

- [ ] **Step 3: Write minimal implementation**

Add to `live_deck_binding.py`:

```python
def resolve_track_identity(
    *,
    title: str,
    artist: str,
    duration_seconds: float,
    candidates: list[dict[str, object]],
) -> dict[str, object]:
    exact = [
        candidate
        for candidate in candidates
        if str(candidate.get("track_title") or "") == title
        and str(candidate.get("track_artist") or "") == artist
        and abs(float(candidate.get("duration_seconds") or 0.0) - duration_seconds) <= 0.5
    ]
    if len(exact) == 1:
        winner = exact[0]
        return {
            "state": "bound",
            "resolved_track_key": str(winner.get("track_key") or ""),
            "match_confidence": 1.0,
        }
    if len(exact) > 1:
        return {"state": "ambiguous", "resolved_track_key": "", "match_confidence": 0.0}
    return {"state": "unbound", "resolved_track_key": "", "match_confidence": 0.0}
```

Add to `PlaybackContext` in `runtime_context.py`:

```python
    def apply_live_binding(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if str(payload.get("state") or "") != "bound":
                return self.snapshot()
            self.track_key = str(payload.get("resolved_track_key") or self.track_key)
            self.track_title = str(payload.get("track_title") or self.track_title)
            self.track_artist = str(payload.get("track_artist") or self.track_artist)
            self.metadata_source = _normalize_metadata_source(
                payload.get("metadata_source", self.metadata_source)
            )
            try:
                self.duration_seconds = max(0.0, float(payload.get("duration_seconds") or self.duration_seconds))
            except (TypeError, ValueError):
                pass
            try:
                self.playhead_seconds = max(0.0, min(float(payload.get("playhead_seconds") or 0.0), self.duration_seconds))
            except (TypeError, ValueError):
                pass
            self.server_time = time.time()
            self.transport_revision += 1
        return self.snapshot()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_live_deck_binding.py -k "resolve_track_identity" -v && pytest tests/unit/test_runtime_control_plane_integration.py -k "apply_live_binding" -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/photonic_synesthesia/platform/live_deck_binding.py src/photonic_synesthesia/platform/runtime_context.py tests/unit/test_live_deck_binding.py tests/unit/test_runtime_control_plane_integration.py
git commit -m "feat: add live deck track resolution and playback binding"
```

## Task 4: Add Ingest Service and Manual Test Adapter

**Files:**
- Create: `src/photonic_synesthesia/platform/live_deck_ingest.py`
- Modify: `src/photonic_synesthesia/core/config.py`
- Modify: `src/photonic_synesthesia/platform/__init__.py`
- Test: `tests/unit/test_live_deck_ingest.py`

- [ ] **Step 1: Write the failing test**

```python
from photonic_synesthesia.platform.live_deck_ingest import (
    LiveDeckIngestService,
    ManualTestIngestAdapter,
)
from photonic_synesthesia.platform.live_deck_models import LiveDeckFact


def test_manual_adapter_overrides_live_snapshot_only_when_enabled() -> None:
    service = LiveDeckIngestService()
    service.publish_live_snapshot([LiveDeckFact(player_number=3, master=True, on_air=True, updated_at=100.0)])
    adapter = ManualTestIngestAdapter(service)

    adapter.publish_test_snapshot([LiveDeckFact(player_number=4, master=True, on_air=True, updated_at=101.0)])
    assert service.current_snapshot().decks[0].player_number == 3

    adapter.set_enabled(True)
    adapter.publish_test_snapshot([LiveDeckFact(player_number=4, master=True, on_air=True, updated_at=101.0)])
    assert service.current_snapshot().decks[0].player_number == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_live_deck_ingest.py -v`

Expected: FAIL with missing ingest service module/classes.

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock

from photonic_synesthesia.platform.live_deck_models import LiveDeckFact, LiveDeckSnapshot


@dataclass(slots=True)
class LiveDeckIngestService:
    _lock: Lock = field(default_factory=Lock, repr=False)
    _live_snapshot: LiveDeckSnapshot = field(default_factory=LiveDeckSnapshot)
    _test_snapshot: LiveDeckSnapshot = field(default_factory=LiveDeckSnapshot)
    _test_mode_enabled: bool = False

    def publish_live_snapshot(self, decks: list[LiveDeckFact]) -> None:
        with self._lock:
            self._live_snapshot = LiveDeckSnapshot(decks=list(decks))

    def publish_test_snapshot(self, decks: list[LiveDeckFact]) -> None:
        with self._lock:
            self._test_snapshot = LiveDeckSnapshot(decks=list(decks))

    def set_test_mode_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._test_mode_enabled = bool(enabled)

    def current_snapshot(self) -> LiveDeckSnapshot:
        with self._lock:
            return self._test_snapshot if self._test_mode_enabled else self._live_snapshot


class ManualTestIngestAdapter:
    def __init__(self, service: LiveDeckIngestService) -> None:
        self._service = service

    def set_enabled(self, enabled: bool) -> None:
        self._service.set_test_mode_enabled(enabled)

    def publish_test_snapshot(self, decks: list[LiveDeckFact]) -> None:
        self._service.publish_test_snapshot(decks)
```

Extend `ProDJLinkConfig` in `core/config.py`:

```python
class ProDJLinkConfig(BaseModel):
    enabled: bool = False
    ingest_mode: str = "tcnet"
    freshness_threshold_seconds: float = 0.5
    listen_host: str = "127.0.0.1"
    keepalive_port: int = 50000
    status_port: int = 50001
    beat_port: int = 50002
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_live_deck_ingest.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/photonic_synesthesia/platform/live_deck_ingest.py src/photonic_synesthesia/core/config.py src/photonic_synesthesia/platform/__init__.py tests/unit/test_live_deck_ingest.py
git commit -m "feat: add live deck ingest service and test adapter"
```

## Task 5: Add Web Endpoints and UI Status/Test Mode

**Files:**
- Modify: `src/photonic_synesthesia/ui/web_panel.py`
- Modify: `src/photonic_synesthesia/ui/static/mock_control_plane.js`
- Test: `tests/unit/test_web_panel.py`

- [ ] **Step 1: Write the failing test**

```python
def test_live_binding_status_endpoint_returns_binding_state(client) -> None:
    response = client.get("/api/live/binding")
    assert response.status_code == 200
    body = response.json()
    assert "binding_status" in body
    assert "test_mode_enabled" in body


def test_manual_test_mode_endpoint_toggles_ingest_override(client) -> None:
    response = client.post(
        "/api/live/binding/test-mode",
        json={"enabled": True, "decks": [{"player_number": 4, "master": True, "on_air": True, "updated_at": 100.0}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["test_mode_enabled"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_web_panel.py -k "live_binding_status or manual_test_mode" -v`

Expected: FAIL with missing routes.

- [ ] **Step 3: Write minimal implementation**

Add to `web_panel.py`:

```python
    @app.get("/api/live/binding")
    async def live_binding_status() -> dict[str, Any]:
        ingest = getattr(app.state, "live_deck_ingest", None)
        status = getattr(app.state, "live_binding_status", None)
        return {
            "binding_status": status.model_dump(mode="json") if status is not None else {},
            "test_mode_enabled": bool(getattr(ingest, "_test_mode_enabled", False)) if ingest is not None else False,
        }

    @app.post("/api/live/binding/test-mode")
    async def update_live_binding_test_mode(request: dict[str, Any]) -> dict[str, Any]:
        ingest = app.state.live_deck_ingest
        ingest.set_test_mode_enabled(bool(request.get("enabled")))
        return {
            "binding_status": getattr(app.state, "live_binding_status", {}).model_dump(mode="json"),
            "test_mode_enabled": bool(request.get("enabled")),
        }
```

Add to `mock_control_plane.js`:

```javascript
async function refreshLiveBinding() {
  appState.liveBinding = await api("/api/live/binding");
}

function renderLiveBindingStatus() {
  if (!elements.playbackPanel || !appState.liveBinding) {
    return;
  }
  const status = appState.liveBinding.binding_status || {};
  const mode = appState.liveBinding.test_mode_enabled ? "TEST MODE" : "LIVE MODE";
  const badge = `${String(status.state || "unbound").toUpperCase()} · ${mode}`;
  const meta = status.authority_player ? `Deck ${status.authority_player}` : "No authority deck";
  const banner = document.createElement("div");
  banner.className = "live-binding-banner";
  banner.textContent = `${badge} · ${meta}`;
  elements.playbackPanel.prepend(banner);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_web_panel.py -k "live_binding_status or manual_test_mode" -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/photonic_synesthesia/ui/web_panel.py src/photonic_synesthesia/ui/static/mock_control_plane.js tests/unit/test_web_panel.py
git commit -m "feat: add live binding status and test mode controls"
```

## Task 6: Wire Auto-Bind Evaluation into Runtime and Verify End-to-End

**Files:**
- Modify: `src/photonic_synesthesia/platform/live_deck_binding.py`
- Modify: `src/photonic_synesthesia/ui/web_panel.py`
- Modify: `tests/unit/test_runtime_control_plane_integration.py`
- Modify: `tests/unit/test_web_panel.py`

- [ ] **Step 1: Write the failing test**

```python
def test_live_binding_pipeline_updates_playback_context_from_authority_deck() -> None:
    ingest = LiveDeckIngestService()
    ctx = PlaybackContext(file_path="", file_name="Live Track", duration_seconds=0.0, track_title="Live Track")
    ingest.publish_live_snapshot(
        [LiveDeckFact(player_number=3, track_title="Age of Love", track_artist="ARTBAT / Pete Tong", duration_seconds=445.4, playhead_seconds=183.2, master=True, on_air=True, updated_at=100.0)]
    )

    status = evaluate_and_apply_live_binding(
        playback_context=ctx,
        ingest_service=ingest,
        now=100.1,
        candidates=[{"track_key": "ARTBAT / Pete Tong|Age of Love", "track_title": "Age of Love", "track_artist": "ARTBAT / Pete Tong", "duration_seconds": 445.4}],
    )

    snapshot = ctx.snapshot()
    assert status.state == "bound"
    assert snapshot["track_title"] == "Age of Love"
    assert snapshot["playhead_seconds"] == 183.2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_runtime_control_plane_integration.py -k "live_binding_pipeline" -v`

Expected: FAIL with missing orchestration function.

- [ ] **Step 3: Write minimal implementation**

Add orchestration helper to `live_deck_binding.py`:

```python
def evaluate_and_apply_live_binding(
    *,
    playback_context: Any,
    ingest_service: Any,
    now: float,
    candidates: list[dict[str, object]],
) -> BindingStatus:
    engine = LiveDeckAutoBindEngine()
    snapshot = ingest_service.current_snapshot()
    status = engine.evaluate(snapshot.decks, now=now)
    if status.state != "bound" or status.authority_player is None:
        return status
    authority = next(deck for deck in snapshot.decks if deck.player_number == status.authority_player)
    resolved = resolve_track_identity(
        title=authority.track_title,
        artist=authority.track_artist,
        duration_seconds=authority.duration_seconds,
        candidates=candidates,
    )
    if resolved["state"] != "bound":
        return BindingStatus(
            state=str(resolved["state"]),
            reason="track resolution failed",
            authority_player=authority.player_number,
            resolved_track_key="",
            match_confidence=float(resolved.get("match_confidence", 0.0)),
            last_update_at=authority.updated_at,
        )
    playback_context.apply_live_binding(
        {
            "state": "bound",
            "resolved_track_key": resolved["resolved_track_key"],
            "track_title": authority.track_title,
            "track_artist": authority.track_artist,
            "duration_seconds": authority.duration_seconds,
            "playhead_seconds": authority.playhead_seconds,
            "metadata_source": "pro_dj_link",
        }
    )
    return BindingStatus(
        state="bound",
        reason="authoritative deck resolved",
        authority_player=authority.player_number,
        resolved_track_key=str(resolved["resolved_track_key"]),
        match_confidence=float(resolved.get("match_confidence", 0.0)),
        last_update_at=authority.updated_at,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_runtime_control_plane_integration.py -k "live_binding_pipeline" -v`

Expected: PASS

- [ ] **Step 5: Run focused regression slice**

Run:

```bash
pytest tests/unit/test_live_deck_binding.py tests/unit/test_live_deck_ingest.py tests/unit/test_runtime_control_plane_integration.py tests/unit/test_web_panel.py -v
```

Expected: PASS for the new live-binding coverage plus no regressions in touched runtime/web tests.

- [ ] **Step 6: Commit**

```bash
git add src/photonic_synesthesia/platform/live_deck_binding.py src/photonic_synesthesia/ui/web_panel.py tests/unit/test_runtime_control_plane_integration.py tests/unit/test_web_panel.py
git commit -m "feat: wire live deck auto-bind through runtime"
```

## Self-Review

### Spec coverage

- Ingest boundary: covered by Tasks 1 and 4.
- Authority election: covered by Task 2.
- Track resolution: covered by Task 3.
- `PlaybackContext` integration: covered by Tasks 3 and 6.
- UI status model: covered by Task 5.
- Manual test mode: covered by Tasks 4 and 5.
- Fail-closed states: covered by Tasks 2, 3, and 6.

### Placeholder scan

- No `TBD`, `TODO`, or “implement later” markers remain.
- Each task names exact files and explicit commands.
- Every code step includes concrete code.

### Type consistency

- Shared names used consistently across tasks:
  - `LiveDeckFact`
  - `BindingStatus`
  - `LiveDeckAutoBindEngine`
  - `LiveDeckIngestService`
  - `ManualTestIngestAdapter`
  - `PlaybackContext.apply_live_binding`

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-20-live-deck-auto-bind.md`.

Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
