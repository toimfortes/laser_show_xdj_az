"""Canonical DMX universe sizing and indexing helpers."""

from __future__ import annotations

DMX_START_CODE = 0x00
DMX_START_CODE_INDEX = 0
DMX_CHANNEL_COUNT = 512
DMX_CHANNEL_MIN = 1
DMX_CHANNEL_MAX = DMX_CHANNEL_COUNT
DMX_UNIVERSE_SIZE = DMX_CHANNEL_COUNT + 1


def create_universe_buffer() -> bytearray:
    """Create a DMX universe buffer including start code + 512 channels."""
    universe = bytearray(DMX_UNIVERSE_SIZE)
    universe[DMX_START_CODE_INDEX] = DMX_START_CODE
    return universe


def is_valid_dmx_channel(channel: int) -> bool:
    """Return True when a channel index is a valid 1-based DMX slot."""
    return DMX_CHANNEL_MIN <= channel <= DMX_CHANNEL_MAX


def extract_channel_payload(universe: bytes) -> bytes:
    """Return the 512-channel payload from a full universe buffer."""
    return universe[DMX_CHANNEL_MIN:DMX_UNIVERSE_SIZE]
