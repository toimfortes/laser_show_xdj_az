"""Pinning tests for the post-crash fixes (F-LOCK, F-HASH, F-EXEC, F-TIMEOUT, F-LOG).

Each test pins one invariant from the cycle-3 destructive review so a
future refactor can't silently re-introduce the catastrophic crash
mode.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from photonic_synesthesia.platform.runtime_context import (  # noqa: E402
    PlaybackContext,
    clear_shared_playback_context,
    set_shared_playback_context,
)
from photonic_synesthesia.ui.web_panel import create_app  # noqa: E402


def _ctx_with_section() -> PlaybackContext:
    ctx = PlaybackContext(file_path="/tmp/x.wav", file_name="x.wav", duration_seconds=60.0)
    ctx.replace_show_sections([
        {"id": "sec-0", "section_role": "intro", "start_seconds": 0.0, "end_seconds": 60.0,
         "cue_recipe": {}, "laser_program": {}},
    ])
    return ctx


# --- F-LOCK: graph tick MUST NOT block on disk I/O ------------------------

def test_f_lock_disk_io_runs_outside_main_lock(tmp_path, monkeypatch) -> None:
    """F-LOCK: `_persist_show_plan_locked` MUST run while `_lock` is
    released, otherwise the 50 Hz graph tick blocks on disk I/O.

    Strategy: install a save callback that records whether `_lock` was
    held when it ran. The callback acquires `_lock` (non-blocking
    `acquire(blocking=False)`); if it succeeds, the lock was free and
    the persistence ran outside the lock.
    """
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    ctx = _ctx_with_section()
    lock_was_free_during_save = []

    def _save_callback(payload):
        # If we can acquire `_lock` non-blocking, it was released before
        # this callback ran (which is the F-LOCK invariant).
        acquired = ctx._lock.acquire(blocking=False)
        lock_was_free_during_save.append(acquired)
        if acquired:
            ctx._lock.release()
        return None

    ctx._save_callback = _save_callback
    ctx.replace_show_sections([{"id": "sec-1", "start_seconds": 0.0, "end_seconds": 60.0}])
    assert lock_was_free_during_save and all(lock_was_free_during_save), (
        "F-LOCK violated: persist callback ran while `_lock` was still held"
    )


# --- F-HASH: hash recompute only fires on actual intent expiry ------------

def test_f_hash_steady_state_transport_does_not_recompute_hash() -> None:
    """F-HASH: at steady state (no intent expiry), `update_transport`
    must NOT call `_recompute_authored_hash_locked`. The previous bug
    burned 24 ms/sec of CPU recomputing an unchanged hash."""
    ctx = _ctx_with_section()
    initial_hash = ctx._authored_hash
    initial_rev = ctx._timeline_flag_revision

    # Run 50 transport ticks at steady state — no intents to expire.
    for i in range(50):
        ctx.update_transport(
            playhead_seconds=10.0 + i * 0.02, playing=True, finished=False,
            realtime=True, speed=1.0,
        )

    # Hash and revision MUST NOT have changed.
    assert ctx._authored_hash == initial_hash
    assert ctx._timeline_flag_revision == initial_rev


def test_f_hash_intent_expiry_does_recompute_hash() -> None:
    """F-HASH negative case: when an intent DOES expire,
    `_recompute_authored_hash_locked` must fire (hash moves)."""
    ctx = _ctx_with_section()
    ctx._save_callback = lambda payload: None  # avoid disk I/O
    # Apply at playhead=5.0 with TTL "at:5.4" — alive at apply, expires
    # on the next transport tick.
    ctx.update_transport(playhead_seconds=5.0, playing=True, finished=False, realtime=True, speed=1.0)
    ctx.apply_operator_intent(
        intent="brighten", scope="track", target="all", amount=0.5,
        expires_at="at:5.4",
    )
    assert len(ctx.operator_intents) == 1, "intent should be active at apply time"
    initial_hash = ctx._authored_hash
    # Tick past the TTL — intent must expire AND hash must recompute.
    ctx.update_transport(playhead_seconds=5.5, playing=True, finished=False, realtime=True, speed=1.0)
    assert len(ctx.operator_intents) == 0, "intent should have expired"
    assert ctx._authored_hash != initial_hash, (
        "F-HASH negative case: intent expired but hash did not recompute"
    )


# --- F-EXEC + F-TIMEOUT: regen runs on dedicated executor with timeout ----

def test_f_timeout_regen_callback_that_hangs_raises_within_5_seconds() -> None:
    """F-TIMEOUT: a wedged `_regenerate_callback` MUST raise RuntimeError
    within ~5s rather than blocking forever.

    Cycle-3-rev-2 R7: the regen slot stays held until the worker
    eventually returns. We use a `threading.Event` so the test can
    release the worker after asserting the timeout fires; otherwise
    subsequent tests would see 'regeneration already in flight'
    errors for the duration of the leaked slot.
    """
    import threading
    ctx = _ctx_with_section()
    stop = threading.Event()

    def _hanging_callback(mode, variance):
        stop.wait(60.0)  # release when test signals OR 60s safety cap
        return [{"id": "sec-99", "section_role": "intro", "start_seconds": 0.0, "end_seconds": 60.0}]

    ctx._regenerate_callback = _hanging_callback
    ctx._save_callback = lambda payload: None
    start = time.perf_counter()
    try:
        with pytest.raises(RuntimeError, match="timed out"):
            ctx.set_selection_mode("ai_assisted")
        elapsed = time.perf_counter() - start
        assert 4.5 < elapsed < 7.0, (
            f"F-TIMEOUT bound violated: expected ~5s, got {elapsed:.1f}s"
        )
    finally:
        # Signal the hanging worker to exit so the regen slot releases
        # and subsequent tests can run without "regen already in flight".
        stop.set()
        # Wait deterministically for the slot to be released by the
        # worker's done-callback (rather than relying on a fixed sleep).
        from photonic_synesthesia.platform.runtime_context import _REGEN_INFLIGHT
        for _ in range(50):
            if _REGEN_INFLIGHT.acquire(blocking=False):
                _REGEN_INFLIGHT.release()
                break
            time.sleep(0.05)


def test_f_timeout_second_regen_returns_inflight_error_while_first_hangs() -> None:
    """Cycle-3-rev-2 R7: while a regen is in flight (even if hung),
    a second regen attempt must return RuntimeError immediately
    instead of spawning another concurrent worker. Closes the
    OS-level CPU starvation Gemini flagged."""
    import threading
    ctx = _ctx_with_section()
    stop = threading.Event()
    started = threading.Event()

    def _hanging_callback(mode, variance):
        started.set()
        stop.wait(60.0)
        return [{"id": "sec-99", "section_role": "intro", "start_seconds": 0.0, "end_seconds": 60.0}]

    ctx._regenerate_callback = _hanging_callback
    ctx._save_callback = lambda payload: None

    def _first_regen():
        try:
            ctx.set_selection_mode("ai_assisted")
        except RuntimeError:
            pass  # expected timeout

    first_thread = threading.Thread(target=_first_regen, daemon=True)
    try:
        first_thread.start()
        # Wait until the first regen actually starts holding the slot.
        assert started.wait(2.0), "first regen never started"
        # Second attempt must fail-fast with the in-flight error
        # (not block waiting for the first to finish).
        start = time.perf_counter()
        with pytest.raises(RuntimeError, match="already in flight"):
            ctx.set_selection_variance(0.5)
        elapsed = time.perf_counter() - start
        assert elapsed < 0.5, (
            f"in-flight refusal must be immediate; took {elapsed:.2f}s"
        )
    finally:
        stop.set()
        first_thread.join(timeout=2.0)
        time.sleep(0.2)


# --- F-LOG: every endpoint emits structured logs --------------------------

def test_f_log_endpoint_emits_request_and_response_logs(monkeypatch) -> None:
    """F-LOG: every endpoint logs `endpoint_request` on entry and
    `endpoint_response` on exit. structlog is in use so we patch the
    in-repo `logger` directly to capture calls (caplog only sees stdlib
    logging which structlog bypasses)."""
    from photonic_synesthesia.ui import web_panel
    captured: list[tuple[str, dict]] = []

    class _CaptureLogger:
        def info(self, event, **kwargs): captured.append(("info", {"event": event, **kwargs}))
        def warning(self, event, **kwargs): captured.append(("warning", {"event": event, **kwargs}))
        def error(self, event, **kwargs): captured.append(("error", {"event": event, **kwargs}))
        def debug(self, event, **kwargs): captured.append(("debug", {"event": event, **kwargs}))
        def exception(self, event, **kwargs): captured.append(("exception", {"event": event, **kwargs}))

    monkeypatch.setattr(web_panel, "logger", _CaptureLogger())
    ctx = _ctx_with_section()
    set_shared_playback_context(ctx)
    try:
        client = TestClient(web_panel.create_app())
        r = client.get("/api/operator/workspace")
        assert r.status_code == 200
    finally:
        clear_shared_playback_context()
    events = [c for c in captured if c[1].get("op") == "GET:/api/operator/workspace"]
    assert any(c[1]["event"] == "endpoint_request" for c in events), (
        f"no endpoint_request for workspace; captured={captured!r}"
    )
    response_events = [c for c in events if c[1]["event"] == "endpoint_response"]
    assert response_events, "no endpoint_response for workspace"
    # Duration was recorded.
    assert "duration_ms" in response_events[0][1]


def test_low1_endpoint_log_captures_path_params_alongside_request_body(monkeypatch) -> None:
    """Cycle-4 Review B LOW-1: the `@log_endpoint` decorator now records
    BOTH the request body AND path/query params in the
    `endpoint_request` log line. Pre-fix only captured the first
    BaseModel arg, so PATCH `/api/mock/fixtures/{fixture_id}` logged
    `changes=...` but dropped `fixture_id`.
    """
    from photonic_synesthesia.ui import web_panel
    captured: list[dict] = []

    class _Capture:
        def info(self, event, **kwargs): captured.append({"event": event, **kwargs})
        def warning(self, event, **kwargs): pass
        def error(self, event, **kwargs): pass
        def debug(self, event, **kwargs): pass
        def exception(self, event, **kwargs): pass

    monkeypatch.setattr(web_panel, "logger", _Capture())
    ctx = _ctx_with_section()
    set_shared_playback_context(ctx)
    try:
        client = TestClient(web_panel.create_app())
        # PATCH a fixture: body is `{changes: {...}}`, path has `fixture_id`.
        state = client.get("/api/mock/state").json()
        fid = state["fixtures"][0]["id"]
        r = client.patch(
            f"/api/mock/fixtures/{fid}",
            json={"changes": {"intensity": 0.5}},
        )
        assert r.status_code == 200
    finally:
        clear_shared_playback_context()
    patch_request = next(
        (c for c in captured
         if c["event"] == "endpoint_request"
         and c.get("op") == "PATCH:/api/mock/fixtures/{fixture_id}"),
        None,
    )
    assert patch_request is not None, "no endpoint_request for PATCH fixture"
    # Body (BaseModel) captured under `request`.
    assert patch_request["request"] == {"changes": {"intensity": 0.5}}
    # Path params captured under `params`.
    assert patch_request["params"] is not None
    assert patch_request["params"].get("fixture_id") == fid


def test_review_b_high6_duplicate_patch_with_same_args_does_not_retrigger_regen() -> None:
    """Cycle-4 post-merge audit Review B HIGH-6: a duplicate PATCH with
    the same selection_mode value (client timeout → retry scenario)
    MUST NOT retrigger the regen. The `normalized_mode == current_mode`
    short-circuit in `_regenerate_selection` closes this by design;
    this test pins it so future refactors can't regress the guarantee.
    """
    ctx = _ctx_with_section()
    call_count = {"n": 0}

    def _counting_regen(mode, variance):
        call_count["n"] += 1
        return [{"id": f"sec-regen-{call_count['n']}",
                 "section_role": "intro", "start_seconds": 0.0, "end_seconds": 60.0}]

    ctx._regenerate_callback = _counting_regen
    ctx._save_callback = lambda payload: None

    # First PATCH: regen runs.
    ctx.set_selection_mode("ai_assisted")
    assert call_count["n"] == 1

    # Client retry with the SAME value: must NOT re-run the regen.
    ctx.set_selection_mode("ai_assisted")
    assert call_count["n"] == 1, (
        "duplicate PATCH with same args must short-circuit, not re-run regen"
    )

    # Different value: regen does run.
    ctx.set_selection_mode("local_ollama_cpu")
    assert call_count["n"] == 2


def test_medium3_ws_reconnect_exponential_backoff_schedule(tmp_path) -> None:
    """Cycle-4 Review B MEDIUM-3: `_wsReconnectDelayMs(attempt)` implements
    exp backoff capped at 30s with ±25% jitter. Pre-fix used a fixed
    1500ms, which meant a down server got 40 req/min from every tab.
    Evaluates the function via node and pins the schedule shape."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available; JS pure-function test skipped")

    # Extract the function, eval it with deterministic Math.random, check
    # the schedule.
    script = r"""
      const fs = require('fs');
      const src = fs.readFileSync(process.argv[2], 'utf8');
      // Extract the _wsReconnectDelayMs function body only.
      const match = src.match(/function _wsReconnectDelayMs\(attempt\)[\s\S]*?^\}/m);
      if (!match) { console.error('function not found'); process.exit(2); }
      eval(match[0]);
      // Force Math.random to 0.5 (jitter=0) for deterministic base values.
      const origRandom = Math.random;
      Math.random = () => 0.5;
      const schedule = [1, 2, 3, 4, 5, 10].map(a => ({ attempt: a, ms: _wsReconnectDelayMs(a) }));
      Math.random = origRandom;
      console.log(JSON.stringify(schedule));
    """
    script_path = tmp_path / "check.js"
    script_path.write_text(script, encoding="utf-8")
    js_src = Path(__file__).resolve().parents[2] / "src/photonic_synesthesia/ui/static/mock_control_plane.js"
    proc = subprocess.run(
        [node, str(script_path), str(js_src)],
        capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0, f"node eval failed: {proc.stderr}"
    import json as _json
    schedule = _json.loads(proc.stdout)
    # Attempts 1-4 double each time; attempts 5+ cap at 30s.
    ms_by_attempt = {entry["attempt"]: entry["ms"] for entry in schedule}
    # With jitter=0 (Math.random=0.5 → (0.5*2-1)=0), base values are exact.
    assert ms_by_attempt[1] == 1500
    assert ms_by_attempt[2] == 3000
    assert ms_by_attempt[3] == 6000
    assert ms_by_attempt[4] == 12000
    assert ms_by_attempt[5] == 24000
    assert ms_by_attempt[10] == 30000  # capped


def test_low2_websocket_live_emits_runtime_snapshots(monkeypatch) -> None:
    """Cycle-4 Review B LOW-2: verify the `/ws/live` websocket emits
    runtime snapshots on a short cadence. Ping frames are implemented
    server-side at 30s intervals (longer than a test should run); this
    test pins that the happy-path stream of runtime snapshots works
    with the new timeout + ping-loop code structure — a regression of
    the ping loop that broke the send path would fail here.
    """
    from photonic_synesthesia.ui import web_panel
    ctx = _ctx_with_section()
    set_shared_playback_context(ctx)
    try:
        client = TestClient(web_panel.create_app())
        with client.websocket_connect("/ws/live") as ws:
            # Receive at least 2 frames within a reasonable timeout.
            frames = []
            for _ in range(2):
                data = ws.receive_json()
                frames.append(data)
            # All should be runtime snapshots (NOT ping frames — the
            # ping cadence is 30s, well above the test window).
            for frame in frames:
                assert "snapshot_id" in frame, f"expected runtime snapshot, got {frame}"
                assert frame.get("op") != "ping", "did not expect a ping in this window"
    finally:
        clear_shared_playback_context()


def test_f_log_endpoint_records_duration_under_normal_load(monkeypatch) -> None:
    """F-LOG: the `duration_ms` field is populated and bounded for a
    normal-cost endpoint."""
    from photonic_synesthesia.ui import web_panel
    captured: list[dict] = []

    class _CaptureLogger:
        def info(self, event, **kwargs): captured.append({"event": event, **kwargs})
        def warning(self, event, **kwargs): captured.append({"event": event, **kwargs})
        def error(self, event, **kwargs): captured.append({"event": event, **kwargs})
        def debug(self, event, **kwargs): pass
        def exception(self, event, **kwargs): captured.append({"event": event, **kwargs})

    monkeypatch.setattr(web_panel, "logger", _CaptureLogger())
    ctx = _ctx_with_section()
    set_shared_playback_context(ctx)
    try:
        client = TestClient(web_panel.create_app())
        client.get("/api/operator/workspace")
    finally:
        clear_shared_playback_context()
    response = next(
        c for c in captured
        if c["event"] == "endpoint_response" and c.get("op") == "GET:/api/operator/workspace"
    )
    assert isinstance(response["duration_ms"], (int, float))
    assert 0 <= response["duration_ms"] < 1000, "single workspace fetch should be under 1s"
