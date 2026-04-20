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


# Cycle-6 hang-remediation (M2): per-test leak canary.
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
_LEAK_CANARY_ENABLED = os.environ.get("PHOTONIC_LEAK_CANARY", "1") == "1"

# Thread names known to be session-scoped (spawned during collection or
# fixture setup, not per-test). Matching is prefix-based on .name.
_SESSION_THREADS = frozenset({
    "MainThread",
    "pytest",
    "Thread-",  # pytest-asyncio and friends
    "asyncio_",
    "ThreadPoolExecutor-",
})


def _current_ignored_thread_names() -> set[str]:
    return {t.name for t in threading.enumerate()}


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

    before_ids = {t.ident for t in threading.enumerate()}
    yield
    new_daemons = [
        t
        for t in threading.enumerate()
        if t.ident not in before_ids and t.daemon and t.is_alive()
    ]
    # Filter session-scoped threads to avoid false positives from pytest
    # infrastructure.
    leaked = [
        t
        for t in new_daemons
        if not any(t.name.startswith(prefix) for prefix in _SESSION_THREADS)
    ]
    if leaked:
        names = sorted({f"{t.name} (daemon={t.daemon})" for t in leaked})
        pytest.fail(
            "Test leaked daemon thread(s). This is the pattern that caused "
            f"the 2026-04-20 system hang. Leaked: {names}. "
            "Use photonic_synesthesia.core.threadhygiene.join_or_raise() "
            "to surface the leak at its real source.",
            pytrace=False,
        )
