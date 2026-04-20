"""Art-Net packet helpers and transmitter."""

from __future__ import annotations

import socket
import struct

from photonic_synesthesia.dmx.universe import DMX_CHANNEL_COUNT

ARTNET_PORT = 6454
ARTNET_HEADER = b"Art-Net\x00"
ARTNET_OPCODE_DMX = 0x5000
ARTNET_PROTOCOL_VERSION = 14


def build_artdmx_packet(
    universe: int,
    dmx_data: bytes,
    sequence: int = 0,
    physical: int = 0,
) -> bytes:
    """
    Build an ArtDMX packet.

    Expects 512 channels of slot data without DMX start code.
    """
    if len(dmx_data) > DMX_CHANNEL_COUNT:
        raise ValueError(f"ArtDMX payload too large: {len(dmx_data)} bytes")

    payload = dmx_data.ljust(DMX_CHANNEL_COUNT, b"\x00")
    # Length is big-endian per Art-Net spec.
    length = len(payload)

    packet = bytearray()
    packet.extend(ARTNET_HEADER)
    packet.extend(struct.pack("<H", ARTNET_OPCODE_DMX))
    packet.extend(struct.pack(">H", ARTNET_PROTOCOL_VERSION))
    packet.extend(bytes([sequence & 0xFF, physical & 0xFF]))
    packet.extend(struct.pack("<H", universe & 0x7FFF))
    packet.extend(struct.pack(">H", length))
    packet.extend(payload)
    return bytes(packet)


class ArtNetTransmitter:
    """UDP sender for Art-Net DMX packets."""

    def __init__(
        self,
        host: str,
        port: int = ARTNET_PORT,
        broadcast: bool = True,
    ):
        self.host = host
        self.port = port
        self.broadcast = broadcast
        self._socket: socket.socket | None = None

    def open(self) -> None:
        """Open the UDP socket and set broadcast option if requested.

        Cycle-6 E3/H1: previously, if `setsockopt` raised (broadcast
        not permitted, exotic stack, sandbox restrictions), the
        partially configured `sock` fell out of scope unclosed —
        leaking a file descriptor until GC. Now we close the partial
        socket on any exception and re-raise.
        """
        if self._socket is not None:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            if self.broadcast:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except BaseException:
            try:
                sock.close()
            except Exception:
                pass
            raise
        self._socket = sock

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def send_dmx(self, universe: int, dmx_data: bytes, sequence: int = 0) -> None:
        if self._socket is None:
            raise RuntimeError("ArtNetTransmitter is not open")
        packet = build_artdmx_packet(
            universe=universe,
            dmx_data=dmx_data,
            sequence=sequence,
        )
        self._socket.sendto(packet, (self.host, self.port))
