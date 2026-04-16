from __future__ import annotations

import struct

from photonic_synesthesia.laser.ether_dream import (
    _ACK,
    EtherDreamClient,
    EtherDreamStatus,
    pack_begin_command,
    pack_dac_point,
    pack_ping_command,
    pack_prepare_command,
    pack_stop_command,
    pack_write_data_command,
    parse_response,
)


def test_ether_dream_command_packets_have_expected_shapes() -> None:
    assert pack_prepare_command() == b"p"
    assert pack_stop_command() == b"s"
    begin = pack_begin_command(low_water_mark=123, point_rate=30000)
    assert begin[0] == 0x62
    assert len(begin) == 7

    point = pack_dac_point(
        {
            "x": 100,
            "y": -100,
            "r": 255,
            "g": 128,
            "b": 0,
            "blanked": False,
        }
    )
    assert len(point) == 18

    payload = pack_write_data_command(
        [
            {
                "x": 100,
                "y": -100,
                "r": 255,
                "g": 128,
                "b": 0,
                "blanked": False,
            }
        ]
    )
    assert payload[0] == 0x64
    assert len(payload) == 21


def test_ether_dream_response_parser_decodes_ack_status() -> None:
    payload = struct.pack(
        "<BBBBBBHHHHII",
        _ACK,
        0x70,
        1,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        30000,
        10,
    )
    response, command, status = parse_response(payload)
    assert response == _ACK
    assert command == 0x70
    assert status.protocol == 1
    assert status.point_rate == 30000
    assert status.point_count == 10


def test_ether_dream_client_streams_with_prepare_write_and_begin() -> None:
    client = EtherDreamClient.__new__(EtherDreamClient)
    client.host = "127.0.0.1"
    client.port = 7765
    client.timeout_s = 1.0
    client.low_water_mark = 12
    client._socket = object()
    client._prepared = False
    client._playing = False

    sent: list[bytes] = []
    statuses = [
        (_ACK, 0x70, EtherDreamStatus(1, 0, 1, 0, 0, 0, 0, 0, 0, 0)),
        (_ACK, 0x64, EtherDreamStatus(1, 0, 1, 0, 0, 0, 0, 64, 0, 0)),
        (_ACK, 0x62, EtherDreamStatus(1, 0, 2, 0, 0, 1, 0, 64, 24000, 0)),
        (_ACK, 0x3F, EtherDreamStatus(1, 0, 2, 0, 0, 1, 0, 64, 24000, 16)),
    ]

    def fake_send(payload: bytes, *, expected_command: int) -> tuple[int, int, EtherDreamStatus]:
        sent.append(payload)
        response = statuses.pop(0)
        assert response[1] == expected_command
        return response

    client.connect = lambda: None
    client._send = fake_send

    frame = {
        "fixture_id": "laser-main",
        "profile_name": "laser_aucd_cx338b_hybrid",
        "geometry_family": "fan",
        "color_mode": "morph",
        "target_bias": "mid_air",
        "point_count": 1,
        "repeat": True,
        "points": [
            {
                "x": 100,
                "y": -100,
                "r": 255,
                "g": 0,
                "b": 255,
                "blanked": False,
            }
        ],
    }

    client.ensure_streaming(frame, point_rate=24000)
    status = client.ping()

    assert status.playback_state == 2
    assert sent[0] == pack_prepare_command()
    assert sent[1][0] == 0x64
    assert sent[2] == pack_begin_command(low_water_mark=12, point_rate=24000)
    assert sent[3] == pack_ping_command()
