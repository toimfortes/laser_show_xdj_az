from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from photonic_synesthesia.core.config import (
    DMXConfig,
    FixtureConfig,
    ILDAConfig,
    LaserSafetyConfig,
    Settings,
)
from photonic_synesthesia.core.state import (
    FixtureCommand,
    MusicStructure,
    PhotonicState,
    create_initial_state,
)
from photonic_synesthesia.graph.builder import PhotonicGraph, _SequentialPipeline
from photonic_synesthesia.graph.nodes.dmx_output import DMXOutputNode
from photonic_synesthesia.graph.nodes.ilda_output import ILDADACOutputNode, ILDAOutputNode
from photonic_synesthesia.graph.nodes.laser_vector_interlock import LaserVectorInterlockNode
from photonic_synesthesia.platform import (
    CommandType,
    ControlPlaneStateService,
    OperatorCommand,
    OperatorRole,
)


class _ProgramActiveState:
    def __call__(self, state: PhotonicState) -> PhotonicState:
        state["timestamp"] += 0.1
        state["current_structure"] = MusicStructure.DROP
        state["fused_bpm"] = 126.0
        state["beat_info"]["confidence"] = 1.0
        state["beat_info"]["beat_phase"] = 0.25
        state["audio_features"]["harmonic_change"] = 0.52
        state["audio_features"]["pitch_height"] = 0.61
        state["audio_features"]["timbral_harshness"] = 0.44
        state["director_state"]["laser_aggression"] = 0.82
        state["director_state"]["melodic_smoothness"] = 0.35
        state["director_state"]["color_drive"] = 0.58
        state["director_state"]["laser_motion_energy"] = 0.77
        state["director_state"]["laser_color_energy"] = 0.51
        state["fixture_commands"] = [
            FixtureCommand(
                fixture_id="panel-1",
                fixture_type="panel",
                channel_values={1: 255},
            )
        ]
        return state


def _fixture() -> FixtureConfig:
    return FixtureConfig(
        id="laser-main",
        name="Main Laser",
        type="laser",
        profile="laser_aucd_cx338b_hybrid",
        start_address=1,
        enabled=True,
    )


def test_blackout_command_drives_dmx_and_ilda_safe_in_same_graph_step() -> None:
    fixture = _fixture()
    service = ControlPlaneStateService()
    ilda_output = ILDAOutputNode(
        ILDAConfig(enabled=True, points_per_frame=48),
        [fixture],
        LaserSafetyConfig(y_axis_max=96),
        fixtures_dir=Path("config/fixtures"),
    )
    laser_interlock = LaserVectorInterlockNode(LaserSafetyConfig())
    ilda_transport = ILDADACOutputNode(
        ILDAConfig(enabled=True, transport_type="ether_dream", target_fps=30.0),
        LaserSafetyConfig(),
        [fixture],
    )
    dmx_output = DMXOutputNode(DMXConfig(interface_type="artnet"))
    nodes = {
        "program": _ProgramActiveState(),
        "ilda_output": ilda_output,
        "laser_vector_interlock": laser_interlock,
        "ilda_transport": ilda_transport,
        "dmx_output": dmx_output,
    }
    graph = PhotonicGraph(
        graph=_SequentialPipeline(
            ["program", "ilda_output", "laser_vector_interlock", "ilda_transport", "dmx_output"],
            nodes,
        ),
        settings=Settings(),
        nodes=nodes,
        control_plane_service=service,
    )
    graph._state = create_initial_state()

    service.accept_command(
        OperatorCommand(
            issuer_id="alice",
            session_id="sess-1",
            role=OperatorRole.OPERATOR,
            command_type=CommandType.ARM,
        )
    )

    with patch("photonic_synesthesia.graph.nodes.ilda_output.EtherDreamClient", return_value=MagicMock()) as ctor:
        fake_client = ctor.return_value

        active_state = graph.step()

        active_frame = fake_client.ensure_streaming.call_args.args[0]
        assert active_state["control_state"]["armed_live"] is True
        assert active_state["control_state"]["blackout_active"] is False
        assert active_state["dmx_universe"][1] == 255
        assert any(not point["blanked"] for point in active_frame["points"])
        assert any(point["r"] > 0 or point["g"] > 0 or point["b"] > 0 for point in active_frame["points"])

        service.accept_command(
            OperatorCommand(
                issuer_id="alice",
                session_id="sess-1",
                role=OperatorRole.OPERATOR,
                command_type=CommandType.BLACKOUT,
            )
        )

        blackout_state = graph.step()

    blackout_frame = fake_client.ensure_streaming.call_args.args[0]
    assert blackout_state["control_state"]["blackout_active"] is True
    assert blackout_state["dmx_universe"][1] == 0
    assert all(point["blanked"] for point in blackout_frame["points"])
    assert all(point["r"] == 0 and point["g"] == 0 and point["b"] == 0 for point in blackout_frame["points"])
