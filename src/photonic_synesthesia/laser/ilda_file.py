"""ILDA `.ild` file writer utilities."""

from __future__ import annotations

import struct

from photonic_synesthesia.core.state import ILDAFrame

_ILDA_MAGIC = b"ILDA"
_FORMAT_TRUECOLOR_2D = 5


def _ascii_field(value: str, length: int = 8) -> bytes:
    encoded = value.encode("ascii", errors="ignore")[:length]
    return encoded.ljust(length, b"\x00")


def _header(
    *,
    format_code: int,
    name: str,
    company: str,
    record_count: int,
    frame_number: int,
    total_frames: int,
    projector_number: int = 0,
) -> bytes:
    return struct.pack(
        ">4s3xB8s8sHHHB",
        _ILDA_MAGIC,
        format_code,
        _ascii_field(name),
        _ascii_field(company),
        record_count,
        frame_number,
        total_frames,
        projector_number,
    ) + b"\x00"


def encode_ild(frames: list[ILDAFrame], *, company: str = "PHOTONIC", projector_number: int = 0) -> bytes:
    """Encode frames as an ILDA true-color 2D file."""
    total_frames = len(frames)
    payload = bytearray()

    for frame_number, frame in enumerate(frames):
        points = frame["points"]
        payload.extend(
            _header(
                format_code=_FORMAT_TRUECOLOR_2D,
                name=frame["geometry_family"][:8],
                company=company,
                record_count=len(points),
                frame_number=frame_number,
                total_frames=total_frames,
                projector_number=projector_number,
            )
        )
        last_index = len(points) - 1
        for index, point in enumerate(points):
            status = 0
            if index == last_index:
                status |= 1 << 7
            if point["blanked"]:
                status |= 1 << 6
            payload.extend(
                struct.pack(
                    ">hhBBBB",
                    int(point["x"]),
                    int(point["y"]),
                    status,
                    int(point["b"]),
                    int(point["g"]),
                    int(point["r"]),
                )
            )

    payload.extend(
        _header(
            format_code=_FORMAT_TRUECOLOR_2D,
            name="EOF",
            company=company,
            record_count=0,
            frame_number=0,
            total_frames=0,
            projector_number=projector_number,
        )
    )
    return bytes(payload)
