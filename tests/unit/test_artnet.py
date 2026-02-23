from photonic_synesthesia.core.config import DMXConfig
from photonic_synesthesia.dmx.artnet import build_artdmx_packet
from photonic_synesthesia.graph.nodes.dmx_output import DMXOutputNode


def test_build_artdmx_packet_layout() -> None:
    data = bytes([7] * 512)
    packet = build_artdmx_packet(universe=0x0123, dmx_data=data, sequence=5)

    assert packet[:8] == b"Art-Net\x00"
    assert packet[8:10] == b"\x00\x50"  # OpOutput / ArtDMX
    assert packet[10:12] == b"\x00\x0e"  # Protocol version 14
    assert packet[12] == 5
    assert packet[13] == 0
    assert packet[14:16] == b"\x23\x01"  # little-endian universe address
    assert packet[16:18] == b"\x02\x00"  # 512 slots
    assert packet[-512:] == data


def test_artnet_universe_address_mapping() -> None:
    config = DMXConfig(
        interface_type="artnet",
        universe=3,
        artnet_subnet=2,
        artnet_net=1,
    )
    node = DMXOutputNode(config)

    assert node._artnet_universe_address() == 0x0123
