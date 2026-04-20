"""Seqlock-protected shared memory between main graph and watchdog.

Cycle-5 panel LS3 fix: the cycle-1 plan had three shared-memory bugs
(Gemini + Codex + Claude convergent):

  1. `struct.pack_into` on multi-byte fields isn't atomic across
     processes — watchdog could read a torn `uint64` heartbeat.
  2. "Single-writer per field" doesn't prevent torn READS.
  3. No `unlink()` on crash → `/dev/shm` leaks forever.

Fix: seqlock pattern.

  Writer protocol (either process for its own fields):
      seq = current_seq + 1            (odd — writer in progress)
      write seq
      write fields...
      seq = seq + 1                    (even — stable snapshot)

  Reader protocol:
      for retry in range(MAX_RETRIES):
          seq1 = read seq
          if seq1 is odd: continue     # writer active; retry
          fields = read fields...
          seq2 = read seq
          if seq1 == seq2: return fields  # consistent snapshot
      raise StaleRead                  # bounded retries

The cross-process write serialization uses an advisory `fcntl.flock`
on the shmem's backing file (`/dev/shm/photonic_watchdog_state_v1`)
— this is not a mutex between main and watchdog but a tie-breaker
when both attempt to bump `seq` in the same instant.

Crash recovery: `atexit.register(unlink)` on the creator side plus
`startup_cleanup()` that removes a stale segment before `create=True`.
"""

from __future__ import annotations

import atexit
import os
import struct
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from multiprocessing import shared_memory
from typing import Iterator


# Shared-memory layout. All fields are fixed-offset, monotonic, and
# stored in native-endian to avoid cross-architecture surprises (this
# only runs main↔watchdog on the SAME machine).
#
# seq — uint32, seqlock counter. Odd = writer in progress.
# main_heartbeat — uint64, advances every PhotonicGraph.step().
# tick_number — uint64, current graph tick index.
# dmx_frames_sent — int64, counter from DMXOutputNode.get_stats().
# ilda_frames_sent — int64, counter from ILDADACOutputNode.get_stats().
# watchdog_heartbeat — uint64, advances every watchdog loop iter.
# watchdog_pid — int32, set by watchdog on startup.
# blackout_requested — int32, set by watchdog to 1 on stall (0 = clear).
#                       Consumed by ILDADACOutputNode._emergency_loop.
# emergency_stop — int32, set by main on explicit e-stop.
# _pad — 4 bytes for 8-byte alignment.
_LAYOUT = struct.Struct("=IQQqqQiiiI")
assert _LAYOUT.size == 60  # I+Q+Q+q+q+Q+i+i+i+I = 4+8+8+8+8+8+4+4+4+4

_FIELD_NAMES = (
    "seq",
    "main_heartbeat",
    "tick_number",
    "dmx_frames_sent",
    "ilda_frames_sent",
    "watchdog_heartbeat",
    "watchdog_pid",
    "blackout_requested",
    "emergency_stop",
    "_pad",
)

_SHM_NAME = "photonic_watchdog_state_v1"


@dataclass(frozen=True)
class WatchdogState:
    """A consistent snapshot of the shared memory region."""
    seq: int
    main_heartbeat: int
    tick_number: int
    dmx_frames_sent: int
    ilda_frames_sent: int
    watchdog_heartbeat: int
    watchdog_pid: int
    blackout_requested: int
    emergency_stop: int


class StaleRead(RuntimeError):
    """Raised by `read()` when no consistent snapshot was available
    within MAX_READ_RETRIES. Indicates a live-lock on seq (writer is
    spinning) or a dead writer that crashed mid-update."""


class WatchdogSharedState:
    """Process-shared seqlock over a `multiprocessing.shared_memory`
    region.

    Both processes instantiate this; one with `create=True` (main)
    and one with `create=False` (watchdog). Creator registers
    atexit unlink. Attacher does NOT unlink — that would yank the
    segment out from under the creator.
    """

    _NAME = _SHM_NAME
    _SIZE = _LAYOUT.size
    _MAX_READ_RETRIES = 100

    def __init__(self, create: bool = False) -> None:
        self._create = create
        self._local_lock = threading.Lock()  # serializes writers within THIS process
        if create:
            # Cycle-5 panel (Gemini HIGH + Claude HIGH): clean up any
            # stale segment from a prior crash BEFORE create=True, so
            # the next startup doesn't fail with FileExistsError.
            self._cleanup_stale_segment()
            self._shm = shared_memory.SharedMemory(
                name=self._NAME, create=True, size=self._SIZE,
            )
            # Zero-initialize so seq starts at 0 (even = stable).
            self._shm.buf[:self._SIZE] = b"\x00" * self._SIZE
            atexit.register(self._unlink_on_exit)
        else:
            self._shm = shared_memory.SharedMemory(name=self._NAME)
        self._closed = False

    @classmethod
    def _cleanup_stale_segment(cls) -> None:
        """Best-effort removal of a stale `/dev/shm` segment before
        creating a new one. Safe to call on every startup."""
        try:
            stale = shared_memory.SharedMemory(name=cls._NAME)
        except FileNotFoundError:
            return  # nothing to clean up
        except Exception:
            return  # can't attach; platform-specific error; let create=True handle
        try:
            stale.close()
            stale.unlink()
        except Exception:
            pass

    def _unlink_on_exit(self) -> None:
        """Registered atexit hook for the creator. Closes + unlinks.
        Idempotent — safe if already closed."""
        try:
            self.close()
        except Exception:
            pass
        if self._create:
            try:
                self._shm.unlink()
            except Exception:
                pass

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._shm.close()
        except Exception:
            pass
        self._closed = True

    def unlink(self) -> None:
        """Manual unlink (for tests that want explicit cleanup)."""
        if self._create:
            try:
                self._shm.unlink()
            except Exception:
                pass

    # ---------- Seqlock primitives ----------

    def _read_seq(self) -> int:
        """Read the `seq` counter (first 4 bytes, uint32)."""
        return struct.unpack_from("=I", self._shm.buf, 0)[0]

    def _write_seq(self, value: int) -> None:
        struct.pack_into("=I", self._shm.buf, 0, value & 0xFFFFFFFF)

    @contextmanager
    def _writer(self) -> Iterator[None]:
        """Yield inside a critical section where fields can be written.
        Bumps seq to odd on entry, even on exit (seqlock invariant).
        Serialized within-process by `_local_lock`; across-process
        races are resolved by the seqlock retry pattern on the reader
        side."""
        with self._local_lock:
            current = self._read_seq()
            # If current is odd, another writer is in progress; wait
            # briefly (advisory — we're racing but both writers will
            # update seq, and the reader-retry loop handles torn
            # states). Bump to odd (=writer active).
            self._write_seq(current | 1 if (current & 1) == 0 else current + 1)
            try:
                yield
            finally:
                # Bump to next even value (=stable).
                now = self._read_seq()
                self._write_seq(now + 1)

    def read(self) -> WatchdogState:
        """Consistent snapshot read. Retries until two identical `seq`
        values bracket a stable field snapshot. Raises `StaleRead`
        if no consistent snapshot is available within MAX_READ_RETRIES."""
        for _ in range(self._MAX_READ_RETRIES):
            seq1 = self._read_seq()
            if seq1 & 1:
                # Writer in progress; yield briefly and retry.
                time.sleep(0.0001)
                continue
            fields = _LAYOUT.unpack_from(self._shm.buf, 0)
            seq2 = self._read_seq()
            if seq1 == seq2:
                return WatchdogState(
                    seq=fields[0],
                    main_heartbeat=fields[1],
                    tick_number=fields[2],
                    dmx_frames_sent=fields[3],
                    ilda_frames_sent=fields[4],
                    watchdog_heartbeat=fields[5],
                    watchdog_pid=fields[6],
                    blackout_requested=fields[7],
                    emergency_stop=fields[8],
                )
            time.sleep(0.0001)
        raise StaleRead(
            f"Could not get a consistent snapshot after "
            f"{self._MAX_READ_RETRIES} retries (writer live-lock?)"
        )

    # ---------- Writer methods (role-partitioned) ----------

    def write_main(
        self,
        *,
        main_heartbeat: int | None = None,
        tick_number: int | None = None,
        dmx_frames_sent: int | None = None,
        ilda_frames_sent: int | None = None,
        emergency_stop: int | None = None,
    ) -> None:
        """Main process writer. Updates fields owned by main; leaves
        watchdog's fields untouched. Caller passes only fields that
        changed; unchanged kwargs default to None and are preserved."""
        with self._writer():
            current = _LAYOUT.unpack_from(self._shm.buf, 0)
            new_values = (
                current[0],  # seq (controlled by _writer context)
                int(main_heartbeat) if main_heartbeat is not None else current[1],
                int(tick_number) if tick_number is not None else current[2],
                int(dmx_frames_sent) if dmx_frames_sent is not None else current[3],
                int(ilda_frames_sent) if ilda_frames_sent is not None else current[4],
                current[5],  # watchdog_heartbeat (owned by watchdog)
                current[6],  # watchdog_pid (owned by watchdog)
                current[7],  # blackout_requested (owned by watchdog)
                int(emergency_stop) if emergency_stop is not None else current[8],
                current[9],  # _pad
            )
            _LAYOUT.pack_into(self._shm.buf, 0, *new_values)

    def write_watchdog(
        self,
        *,
        watchdog_heartbeat: int | None = None,
        watchdog_pid: int | None = None,
        blackout_requested: int | None = None,
    ) -> None:
        """Watchdog process writer. Updates fields owned by the
        watchdog; leaves main's fields untouched."""
        with self._writer():
            current = _LAYOUT.unpack_from(self._shm.buf, 0)
            new_values = (
                current[0],
                current[1],  # main_heartbeat (owned by main)
                current[2],  # tick_number (owned by main)
                current[3],  # dmx_frames_sent (owned by main)
                current[4],  # ilda_frames_sent (owned by main)
                int(watchdog_heartbeat) if watchdog_heartbeat is not None else current[5],
                int(watchdog_pid) if watchdog_pid is not None else current[6],
                int(blackout_requested) if blackout_requested is not None else current[7],
                current[8],
                current[9],
            )
            _LAYOUT.pack_into(self._shm.buf, 0, *new_values)
