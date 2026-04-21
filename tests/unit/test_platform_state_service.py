from photonic_synesthesia.core.state import MusicStructure, create_initial_state
from photonic_synesthesia.platform import (
    CommandType,
    ControlPlaneStateService,
    InMemoryCommandBus,
    OperatorCommand,
    OperatorRole,
)


def test_state_service_updates_snapshot_from_photonic_state() -> None:
    service = ControlPlaneStateService()
    state = create_initial_state()
    state["frame_number"] = 42
    state["fused_bpm"] = 126.5
    state["bpm_source"] = "fused"
    state["current_structure"] = MusicStructure.DROP
    state["structure_confidence"] = 0.9
    state["drop_probability"] = 0.8
    state["beat_info"]["beat_phase"] = 0.25
    state["beat_info"]["confidence"] = 0.95
    state["beat_info"]["downbeat"] = True
    state["scene_state"]["current_scene"] = "drop_intense"
    state["scene_state"]["pending_scene"] = "next_scene"
    state["director_state"]["target_scene"] = "drop_intense"
    state["director_state"]["energy_level"] = 0.85
    state["safety_state"]["ok"] = False
    state["safety_state"]["error_state"] = "watchdog"
    state["safety_state"]["emergency_stop"] = True

    snapshot = service.update_from_photonic_state(state)

    assert snapshot.active_scene_id == "drop_intense"
    assert snapshot.pending_scene_id == "next_scene"
    assert snapshot.semantic_frame.structure == "drop"
    assert snapshot.semantic_frame.bpm == 126.5
    assert snapshot.director_summary.energy_level == 0.85
    assert snapshot.safety_summary.error_state == "watchdog"
    assert snapshot.blackout_active is True
    assert snapshot.diagnostics["frame_number"] == 42


def test_state_service_accept_command_applies_effects() -> None:
    service = ControlPlaneStateService()

    service.accept_command(
        OperatorCommand(
            issuer_id="alice",
            session_id="sess-1",
            role=OperatorRole.OPERATOR,
            command_type=CommandType.SET_GLOBAL_INTENSITY,
            payload={"intensity": 0.4},
        )
    )
    service.accept_command(
        OperatorCommand(
            issuer_id="alice",
            session_id="sess-1",
            role=OperatorRole.OPERATOR,
            command_type=CommandType.LAUNCH_SCENE,
            payload={"scene_id": "intro_ambient"},
        )
    )

    snapshot = service.snapshot()

    assert snapshot.effective_global_intensity == 0.4
    assert snapshot.pending_scene_id == "intro_ambient"


def test_state_service_consumes_command_batch_before_graph_step() -> None:
    service = ControlPlaneStateService()

    service.accept_command(
        OperatorCommand(
            issuer_id="alice",
            session_id="sess-1",
            role=OperatorRole.OPERATOR,
            command_type=CommandType.ARM,
        )
    )
    assert service.snapshot().armed_live is True

    service.commands.publish(
        OperatorCommand(
            issuer_id="alice",
            session_id="sess-1",
            role=OperatorRole.OPERATOR,
            command_type=CommandType.CLEAR_BLACKOUT,
        )
    )
    service.commands.publish(
        OperatorCommand(
            issuer_id="alice",
            session_id="sess-1",
            role=OperatorRole.OPERATOR,
            command_type=CommandType.DISARM,
        )
    )

    control_state = service.consume_control_snapshot_for_graph()

    assert control_state["armed_live"] is False
    assert control_state["blackout_active"] is True
    assert service.commands.backlog() == 0


def test_initial_state_starts_disarmed() -> None:
    state = create_initial_state()

    assert state["control_state"]["armed_live"] is False


def test_command_bus_rejects_publish_when_queue_is_full() -> None:
    bus = InMemoryCommandBus(max_queue=1)

    first = bus.publish(
        OperatorCommand(
            issuer_id="alice",
            session_id="sess-1",
            role=OperatorRole.OPERATOR,
            command_type=CommandType.ARM,
        )
    )
    second = bus.publish(
        OperatorCommand(
            issuer_id="alice",
            session_id="sess-1",
            role=OperatorRole.OPERATOR,
            command_type=CommandType.DISARM,
        )
    )

    assert first.accepted is True
    assert second.accepted is False
    assert bus.backlog() == 1


def test_state_service_does_not_apply_rejected_command_effects() -> None:
    service = ControlPlaneStateService()
    service.commands = InMemoryCommandBus(max_queue=1)

    first = service.accept_command(
        OperatorCommand(
            issuer_id="alice",
            session_id="sess-1",
            role=OperatorRole.OPERATOR,
            command_type=CommandType.ARM,
        )
    )
    second = service.accept_command(
        OperatorCommand(
            issuer_id="alice",
            session_id="sess-1",
            role=OperatorRole.OPERATOR,
            command_type=CommandType.DISARM,
        )
    )

    assert first.accepted is True
    assert second.accepted is False
    assert service.snapshot().armed_live is True
