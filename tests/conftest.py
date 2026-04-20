from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"

if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))


# Cycle-6 hang-remediation (M2 + E2): per-test leak canary.
#
# Yesterday's crash accumulated leaked daemon threads over ~300 tests
# before the CPU-saturation threshold was hit. This fixture turns that
# invisible accumulation into a loud per-test failure — the FIRST test
# that leaks a daemon thread fails, not the 300th.
#
# Default-on since cycle-6 Phase C. Set `PHOTONIC_LEAK_CANARY=0` to
# opt out (useful if a third-party pytest plugin spawns an unavoidable
# daemon during teardown and we need a clean signal on a separate
# failure mode). CI always runs with the canary on.
#
# Cycle-6 E2: the canary now compares thread IDENTs instead of filtering
# by name prefix. Pre-E2 the whitelist included `"Thread-"`, which matches
# Python's default auto-generated name format (`Thread-N`) for any thread
# constructed without `name=`. A test that created
# `threading.Thread(target=..., daemon=True)` without passing `name=`
# would leak a daemon with a default `Thread-N` name — exactly the class
# the canary was designed to catch — and the whitelist let it through.
# Panel v2 (3/3 convergent, Codex + Gemini + Claude) flagged this as a
# CRITICAL canary-bypass. The ident-based approach has no false-negative
# surface because pytest-internal threads are snapshotted at session start
# and every new ident is tested against that snapshot.
_LEAK_CANARY_ENABLED = os.environ.get("PHOTONIC_LEAK_CANARY", "1") == "1"

# Populated by the `_capture_session_baseline_threads` fixture below.
_SESSION_BASELINE_IDENTS: set[int] = set()


@pytest.fixture(scope="session", autouse=True)
def _capture_session_baseline_threads():
    """Snapshot thread idents at session start so the per-test canary
    can distinguish session-scoped threads (pytest-asyncio reactor,
    ThreadPoolExecutor workers, plugin helpers) from test-scoped
    leaks. Any thread not in this baseline that's alive at test
    teardown is a real leak.
    """
    _SESSION_BASELINE_IDENTS.update(t.ident for t in threading.enumerate() if t.ident is not None)
    yield


@pytest.fixture(autouse=True)
def _photonic_thread_leak_canary():
    """Fail loudly if a test leaks a daemon thread.

    Skipped unless `PHOTONIC_LEAK_CANARY=1`. When active, compares the
    set of daemon threads before + after each test; any NEW daemon still
    alive at teardown fails the test with the leaked name. This is the
    single forcing function against yesterday's incident class."""
    if not _LEAK_CANARY_ENABLED:
        yield
        return

    before_ids = {t.ident for t in threading.enumerate() if t.ident is not None}
    yield
    leaked: list[threading.Thread] = []
    for t in threading.enumerate():
        if not t.is_alive() or not t.daemon or t.ident is None:
            continue
        # A thread is a leak IFF it was NOT in the per-test "before"
        # set AND NOT in the session-start baseline. The session
        # baseline covers pytest-asyncio reactors, ThreadPoolExecutor
        # workers from plugins, MainThread, and anything else that
        # spawned during collection.
        if t.ident in before_ids:
            continue
        if t.ident in _SESSION_BASELINE_IDENTS:
            continue
        leaked.append(t)

    if leaked:
        descriptions = sorted({f"{t.name!r} (ident={t.ident}, daemon={t.daemon})" for t in leaked})
        pytest.fail(
            "Test leaked daemon thread(s). This is the pattern that caused "
            f"the 2026-04-20 system hang. Leaked: {descriptions}. "
            "Use photonic_synesthesia.core.threadhygiene.join_or_raise() "
            "to surface the leak at its real source.",
            pytrace=False,
        )
