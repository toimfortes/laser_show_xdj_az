"""Minimal Ether Dream DAC client and packet helpers."""

from __future__ import annotations

import socket
import struct
import threading
from dataclasses import dataclass

from photonic_synesthesia.core.config import ILDAConfig
from photonic_synesthesia.core.state import ILDAFrame, ILDAPoint

_ACK = 0x61
_NAK_FULL = 0x46
_NAK_INVALID = 0x49
_NAK_STOP = 0x21
_STATUS_SIZE = 20
_RESPONSE_SIZE = 22


def _u16(value: int) -> int:
    return max(0, min(65535, int(value)))


def _ilda_to_u16_color(value: int) -> int:
    return _u16(int(value) * 257)


def pack_prepare_command() -> bytes:
    return b"p"


def pack_ping_command() -> bytes:
    return b"?"


def pack_stop_command() -> bytes:
    return b"s"


def pack_emergency_stop_command() -> bytes:
    return b"\x00"


def pack_clear_emergency_command() -> bytes:
    return b"c"


def pack_begin_command(*, low_water_mark: int, point_rate: int) -> bytes:
    return struct.pack("<BHI", 0x62, max(0, min(65535, low_water_mark)), max(1, point_rate))


def pack_dac_point(point: ILDAPoint) -> bytes:
    # Ether Dream blanking is represented by zeroed color/intensity channels.
    # Bit 15 is reserved for point-rate changes, not shutter control.
    control = 0
    blanked = bool(point["blanked"])
    red = 0 if blanked else int(point["r"])
    green = 0 if blanked else int(point["g"])
    blue = 0 if blanked else int(point["b"])
    intensity = 0 if blanked else max(red, green, blue)
    return struct.pack(
        "<HhhHHHHHH",
        control,
        int(point["x"]),
        int(point["y"]),
        _ilda_to_u16_color(red),
        _ilda_to_u16_color(green),
        _ilda_to_u16_color(blue),
        _ilda_to_u16_color(intensity),
        0,
        0,
    )


def pack_write_data_command(points: list[ILDAPoint]) -> bytes:
    header = struct.pack("<BH", 0x64, len(points))
    return header + b"".join(pack_dac_point(point) for point in points)


@dataclass(slots=True)
class EtherDreamStatus:
    protocol: int
    light_engine_state: int
    playback_state: int
    source: int
    light_engine_flags: int
    playback_flags: int
    source_flags: int
    buffer_fullness: int
    point_rate: int
    point_count: int


def parse_response(payload: bytes) -> tuple[int, int, EtherDreamStatus]:
    response, command = struct.unpack_from("<BB", payload, 0)
    status_values = struct.unpack_from("<BBBBHHHHII", payload, 2)
    return response, command, EtherDreamStatus(*status_values)


class EtherDreamClient:
    """Synchronous Ether Dream client safe for multi-thread owners.

    Public methods serialize on an internal RLock so the graph thread
    (streaming frames) and the safety watchdog thread (issuing
    emergency_stop / close) cannot interleave socket writes or corrupt
    the ``_prepared`` / ``_playing`` / ``_current_point_rate`` state
    machine. RLock (not Lock) is used because ``close()`` calls
    ``stop()`` internally while the lock is held.
    """

    def __init__(self, config: ILDAConfig):
        self.host = config.ether_dream_host
        self.port = config.ether_dream_port
        self.timeout_s = config.ether_dream_timeout_s
        self.low_water_mark = config.ether_dream_low_water_mark
        self._lock = threading.RLock()
        self._socket: socket.socket | None = None
        self._prepared = False
        self._playing = False
        self._current_point_rate: int | None = None

    def connect(self) -> None:
        """Connect to the Ether Dream DAC and read its initial broadcast.

        Cycle-6 E3/H3: previously assigned `self._socket = sock` BEFORE
        `_recv_response()`. If recv timed out or the DAC dropped the
        connection mid-handshake, `self._socket` was already set —
        every subsequent `connect()` short-circuited on `if self._socket
        is not None: return`, leaving a poisoned socket retained
        forever and the DAC effectively unrecoverable until process
        restart. Now we keep `sock` local until handshake completes;
        on any error we close it and clear state before re-raising.
        """
        with self._lock:
            if self._socket is not None:
                return
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout_s)
            sock.settimeout(self.timeout_s)
            try:
                # Temporarily attach so `_recv_response` (which reads
                # from `self._socket`) can use it. Roll back on failure.
                self._socket = sock
                self._recv_response()
            except BaseException:
                self._socket = None
                try:
                    sock.close()
                except Exception:
                    pass
                raise

    def close(self) -> None:
        with self._lock:
            if self._socket is None:
                return
            try:
                self.stop()
            except OSError:
                pass
            self._socket.close()
            self._socket = None
            self._prepared = False
            self._playing = False
            self._current_point_rate = None

    def ensure_streaming(self, frame: ILDAFrame, *, point_rate: int) -> None:
        with self._lock:
            self.connect()
            if self._playing and self._current_point_rate != point_rate:
                self.stop()
            if not self._prepared:
                self._send(pack_prepare_command(), expected_command=0x70)
                self._prepared = True
            self._send(pack_write_data_command(frame["points"]), expected_command=0x64)
            if not self._playing:
                self._send(
                    pack_begin_command(low_water_mark=self.low_water_mark, point_rate=point_rate),
                    expected_command=0x62,
                )
                self._playing = True
                self._current_point_rate = point_rate

    def stop(self) -> None:
        with self._lock:
            if self._socket is None or not (self._prepared or self._playing):
                return
            self._send(pack_stop_command(), expected_command=0x73)
            self._prepared = False
            self._playing = False
            self._current_point_rate = None

    def emergency_stop(self) -> None:
        with self._lock:
            self.connect()
            # Emergency stop enters E-stop state even if playback/state is inconsistent.
            self._send(pack_emergency_stop_command(), expected_command=0x00)
            self._prepared = False
            self._playing = False
            self._current_point_rate = None

    def clear_emergency_stop(self) -> None:
        with self._lock:
            if self._socket is None:
                return
            # Clear E-Stop if active; if not active this is a no-op at protocol level.
            try:
                self._send(pack_clear_emergency_command(), expected_command=0x63)
            except OSError:
                pass

    def ping(self) -> EtherDreamStatus:
        with self._lock:
            self.connect()
            _, _, status = self._send(pack_ping_command(), expected_command=0x3F)
            return status

    def _send(self, payload: bytes, *, expected_command: int) -> tuple[int, int, EtherDreamStatus]:
        if self._socket is None:
            raise OSError("Ether Dream socket is not connected")
        self._socket.sendall(payload)
        response, command, status = self._recv_response()
        if command != expected_command:
            raise OSError(f"Unexpected Ether Dream response command {command:#x}")
        if response != _ACK:
            reason = {
                _NAK_FULL: "buffer full",
                _NAK_INVALID: "invalid command/state",
                _NAK_STOP: "stop condition active",
            }.get(response, f"unknown response {response:#x}")
            raise OSError(f"Ether Dream rejected command: {reason}")
        return response, command, status

    def _recv_response(self) -> tuple[int, int, EtherDreamStatus]:
        if self._socket is None:
            raise OSError("Ether Dream socket is not connected")
        payload = b""
        while len(payload) < _RESPONSE_SIZE:
            chunk = self._socket.recv(_RESPONSE_SIZE - len(payload))
            if not chunk:
                raise OSError("Ether Dream connection closed")
            payload += chunk
        return parse_response(payload)
