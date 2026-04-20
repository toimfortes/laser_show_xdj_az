"""Pinning tests for the post-crash fixes (F-LOCK, F-HASH, F-EXEC, F-TIMEOUT, F-LOG).

Each test pins one invariant from the cycle-3 destructive review so a
future refactor can't silently re-introduce the catastrophic crash
mode.
"""

from __future__ import annotations

import time

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
    """F-TIMEOUT: a wedged `_regenerate_callback` MUST NOT hold `_lock`
    indefinitely. The 5-second timeout converts a hang into a
    RuntimeError that the FastAPI handler can return as 400."""
    ctx = _ctx_with_section()

    def _hanging_callback(mode, variance):
        time.sleep(60.0)  # would hang the system if not bounded
        return [{"id": "sec-99", "start_seconds": 0.0, "end_seconds": 60.0}]

    ctx._regenerate_callback = _hanging_callback
    ctx._save_callback = lambda payload: None
    start = time.perf_counter()
    with pytest.raises(RuntimeError, match="timed out"):
        ctx.set_selection_mode("ai_assisted")
    elapsed = time.perf_counter() - start
    assert 4.5 < elapsed < 7.0, (
        f"F-TIMEOUT bound violated: expected ~5s, got {elapsed:.1f}s"
    )


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
