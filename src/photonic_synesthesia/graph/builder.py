"""
Sequential Builder for Photonic Synesthesia.

Constructs the main processing pipeline that orchestrates all
sensor acquisition, analysis, and fixture control nodes.
"""

from __future__ import annotations

import copy
import threading
from threading import Lock
from typing import Any, Callable

from photonic_synesthesia.core.config import Settings
from photonic_synesthesia.core.logging import get_logger
from photonic_synesthesia.core.state import PhotonicState, create_initial_state
from photonic_synesthesia.graph.nodes import (
    AudioSenseNode,
    BeatTrackNode,
    CVSenseNode,
    DirectorIntentNode,
    DMXOutputNode,
    FeatureExtractNode,
    FusionNode,
    ILDADACOutputNode,
    ILDAExportNode,
    ILDAOutputNode,
    InterpreterNode,
    LaserControlNode,
    LaserVectorInterlockNode,
    MidiSenseNode,
    MovingHeadControlNode,
    PanelControlNode,
    SafetyInterlockNode,
    SafetyMonitor,
    SceneSelectNode,
    StructureDetectNode,
)
from photonic_synesthesia.graph.nodes.laser_zone_runtime import LaserZoneRuntimeNode
from photonic_synesthesia.graph.nodes.preposition import PrepositionNode
from photonic_synesthesia.graph.nodes.surface_compositor import SurfaceCompositorNode
from photonic_synesthesia.graph.nodes.trigger_router import TriggerRouterNode
from photonic_synesthesia.platform.runtime_context import get_shared_playback_context
from photonic_synesthesia.platform.state_service import ControlPlaneStateService

logger = get_logger(__name__)


class _SequentialPipeline:
    """Simple deterministic node pipeline with single-pass execution."""

    def __init__(self, node_names: list[str], nodes: dict[str, Any]):
        self._node_names = node_names
        self._nodes = nodes

    def invoke(self, state: PhotonicState) -> PhotonicState:
        current_state = state
        for name in self._node_names:
            node = self._nodes[name]
            current_state = node(current_state)
        return current_state


class PhotonicGraph:
    """
    Wrapper around the deterministic node pipeline for the photonic
    synesthesia system.

    Provides methods for running the graph continuously and managing
    the sensor/output lifecycle.
    """

    def __init__(
        self,
        graph: Any,  # Compiled sequential pipeline
        settings: Settings,
        nodes: dict[str, Any],
        control_plane_service: ControlPlaneStateService | None = None,
        safety_monitor: SafetyMonitor | None = None,
        enable_out_of_process_watchdog: bool | None = None,
    ):
        self.graph = graph
        self.settings = settings
        self.nodes = nodes
        self.safety_monitor = safety_monitor
        self.control_plane_service = control_plane_service
        self._running = False
        self._state = create_initial_state()
        self._state_lock = Lock()
        self.hybrid_pacing = settings.runtime_flags.hybrid_pacing
        self.dual_loop = settings.runtime_flags.dual_loop

        # Cycle-5 panel LS3: out-of-process watchdog. Opt-in via env
        # var `PHOTONIC_WATCHDOG=1` (default off to preserve existing
        # test behavior + single-process deployments). When enabled,
        # the watchdog spawns on start() and SIGKILLs main on
        # hard stalls. Graph tick writes heartbeat to shmem every
        # step(). See `photonic_watchdog/` for the out-of-process
        # module — stdlib-only imports required.
        if enable_out_of_process_watchdog is None:
            import os as _os
            enable_out_of_process_watchdog = _os.environ.get("PHOTONIC_WATCHDOG", "0") == "1"
        self._enable_watchdog = enable_out_of_process_watchdog
        self._watchdog_proc: Any = None  # multiprocessing.Process | None
        self._watchdog_shmem: Any = None  # WatchdogSharedState | None
        self._tick_number = 0

    def start(self) -> None:
        """Start all sensor nodes and begin processing."""
        logger.info("Starting photonic graph")
        self._running = True

        # Start background threads for sensors
        if "audio_sense" in self.nodes:
            self.nodes["audio_sense"].start()
        if "midi_sense" in self.nodes:
            self.nodes["midi_sense"].start()
        if "cv_sense" in self.nodes and hasattr(self.nodes["cv_sense"], "start"):
            self.nodes["cv_sense"].start()
        if "dmx_output" in self.nodes:
            self.nodes["dmx_output"].start()
        if "ilda_output" in self.nodes and hasattr(self.nodes["ilda_output"], "start"):
            self.nodes["ilda_output"].start()
        if "ilda_transport" in self.nodes and hasattr(self.nodes["ilda_transport"], "start"):
            self.nodes["ilda_transport"].start()
        if "safety_interlock" in self.nodes and hasattr(self.nodes["safety_interlock"], "start"):
            self.nodes["safety_interlock"].start()
        if self.safety_monitor is not None:
            self.safety_monitor.start()
        if self._enable_watchdog:
            self._start_out_of_process_watchdog()

    def _start_out_of_process_watchdog(self) -> None:
        """Cycle-5 panel LS3: spawn the GIL-immune watchdog.

        MUST use `spawn` start method. `fork` inherits lock state
        from this process's daemon threads (SafetyMonitor,
        ILDA-Emergency-Output) and can deadlock.
        """
        import multiprocessing
        import os
        import signal as _signal

        try:
            from photonic_watchdog.shmem import WatchdogSharedState
            from photonic_watchdog.loop import watchdog_loop
        except ImportError as exc:
            logger.warning("out_of_process_watchdog_unavailable", error=str(exc))
            self._enable_watchdog = False
            return

        try:
            self._watchdog_shmem = WatchdogSharedState(create=True)
        except Exception as exc:
            logger.warning("watchdog_shmem_init_failed", error=str(exc))
            self._enable_watchdog = False
            return

        # Install SIGUSR1 handler: watchdog's soft-escalation path.
        # Runs in the Python interpreter thread when it next reaches
        # a bytecode boundary. Triggers request_blackout on every
        # output node that supports it.
        #
        # Cycle-6 E1/C2: this handler is async-signal-safe.
        #   - Uses `os.write(2, ...)` instead of `logger.warning`
        #     because structlog acquires internal locks. A signal
        #     landing mid-emit would deadlock if the handler then
        #     tried to re-acquire the same lock.
        #   - Prefers `request_blackout` (pure flag-set) over
        #     `emergency_blackout` (does socket IO on the ILDA DAC).
        #     The ILDA emergency_loop polls the flag every ~50ms and
        #     does the actual hardware actuation there — no need to
        #     do IO from signal context. Shmem `blackout_requested`
        #     poll (set by the watchdog before raising SIGUSR1) is
        #     the backstop if this handler can't run for any reason.
        _SIGUSR1_MSG = b"[signal] SIGUSR1 received: watchdog soft-stall escalation\n"
        _SIGUSR1_ERR = b"[signal] SIGUSR1 handler failed\n"
        _SIGUSR1_NO_METHOD = (
            b"[signal] SIGUSR1: node present but no blackout method "
            b"(rename / refactor regression?)\n"
        )

        def _on_sigusr1(signum: int, frame: Any) -> None:
            try:
                os.write(2, _SIGUSR1_MSG)
            except OSError:
                pass
            for node_name in ("dmx_output", "ilda_output", "ilda_transport"):
                node = self.nodes.get(node_name)
                if node is None:
                    continue
                handler = (
                    getattr(node, "request_blackout", None)
                    or getattr(node, "emergency_blackout", None)
                    or getattr(node, "blackout", None)
                )
                if callable(handler):
                    try:
                        handler()
                    except Exception:  # pragma: no cover — defensive
                        try:
                            os.write(2, _SIGUSR1_ERR)
                        except OSError:
                            pass
                else:
                    # Cycle-6 E8/M3: a node was wired into the graph but
                    # exposes none of the blackout methods. Pre-E8 this
                    # silently no-op'd, masking renames/refactors of the
                    # blackout API across nodes. Surface it so the
                    # missing method is visible in an audit log even
                    # though we can't structlog from signal context.
                    try:
                        os.write(2, _SIGUSR1_NO_METHOD)
                    except OSError:
                        pass

        # Cycle-6 B5: signal.signal() only works in the main thread of
        # the main interpreter. Non-main-thread installation raises
        # ValueError with a confusing message; explicitly detect the
        # case and log at ERROR so the dropped signal channel is
        # visible in audit (vs the prior WARN that blended into
        # normal startup noise). Graceful-degrade behavior unchanged —
        # the SIGKILL path via the watchdog still works without the
        # in-process SIGUSR1 handler.
        if threading.current_thread() is not threading.main_thread():
            logger.error(
                "sigusr1_install_skipped_non_main_thread",
                thread=threading.current_thread().name,
                note=(
                    "_start_out_of_process_watchdog must run in the main "
                    "thread for the SIGUSR1 soft-escalation handler to "
                    "install. Hard-stall SIGKILL via watchdog is still "
                    "functional, but soft-stall blackout is degraded."
                ),
            )
        else:
            try:
                _signal.signal(_signal.SIGUSR1, _on_sigusr1)
            except (OSError, ValueError) as exc:
                # Windows or a restricted runtime (Docker with some
                # syscall filters) — the SIGKILL path still works via
                # the watchdog.
                logger.warning("sigusr1_install_failed", error=str(exc))

        ctx = multiprocessing.get_context("spawn")
        self._watchdog_proc = ctx.Process(
            target=watchdog_loop,
            args=(os.getpid(),),
            name="photonic-watchdog",
            daemon=True,
        )
        self._watchdog_proc.start()

        # Cycle-5 panel LS3 (Kilo F4): give the in-process ILDA emergency
        # thread visibility into the watchdog's `blackout_requested` flag
        # so a soft-stall escalation produces DAC blank frames even if
        # SIGUSR1 is still pending delivery on the main thread.
        ilda_node = self.nodes.get("ilda_output")
        if ilda_node is not None and hasattr(ilda_node, "attach_watchdog_shmem"):
            ilda_node.attach_watchdog_shmem(self._watchdog_shmem)
        ilda_transport = self.nodes.get("ilda_transport")
        if ilda_transport is not None and hasattr(ilda_transport, "attach_watchdog_shmem"):
            ilda_transport.attach_watchdog_shmem(self._watchdog_shmem)

        logger.info("out_of_process_watchdog_started", pid=self._watchdog_proc.pid)

    def stop(self) -> None:
        """Stop all processing and clean up resources.

        Cycle-6 C2/stop-order: per-node shutdown is wrapped in
        try/except. Pre-C2 the first node whose stop() raised (now
        a real possibility thanks to `join_or_raise`) prevented
        every later node from being torn down — a single wedged
        cv_sense worker could leak the DMX serial, the ILDA DAC,
        and the feature-extract ProcessPool. Isolating each stop
        call means a loud failure in one node doesn't cascade into
        a silent leak across the rest.
        """
        logger.info("Stopping photonic graph")
        self._running = False

        # Ordered list of (label, callable) — ordering matters for
        # data-flow dependencies (stop sources before sinks so the
        # sinks don't wedge on an unblocked producer), but each call
        # is individually protected.
        shutdown_steps: list[tuple[str, Callable[[], None]]] = []

        def _add(label: str, node_key: str, method_name: str = "stop") -> None:
            node = self.nodes.get(node_key)
            if node is None:
                return
            method = getattr(node, method_name, None)
            if not callable(method):
                return
            shutdown_steps.append((label, method))

        _add("audio_sense", "audio_sense")
        _add("midi_sense", "midi_sense")
        _add("cv_sense", "cv_sense")
        _add("ilda_transport", "ilda_transport")
        _add("safety_interlock", "safety_interlock")
        if self.safety_monitor is not None:
            shutdown_steps.append(("safety_monitor", self.safety_monitor.stop))
        _add("ilda_output", "ilda_output")
        _add("dmx_output", "dmx_output")
        # Cycle-5 HIGH: ilda_export flushes its accumulated `.ild`
        # timeline to disk on stop(). The file represents the whole
        # show — writing it once here is O(N); writing it per tick
        # was O(N²) and unbounded in memory.
        _add("ilda_export", "ilda_export")
        # Cycle-1 Review A: feature_extract owns a ProcessPool worker
        # (heavy DSP off the hot path). Shut it down on graph stop so
        # the child process exits cleanly instead of leaking.
        _add("feature_extract", "feature_extract", method_name="close")

        failed: list[tuple[str, BaseException]] = []
        for label, call in shutdown_steps:
            try:
                call()
            except BaseException as exc:  # noqa: BLE001 — teardown must continue
                failed.append((label, exc))
                logger.exception("node_stop_failed", node=label)

        if failed:
            logger.error(
                "graph_stop_completed_with_failures",
                count=len(failed),
                nodes=[label for label, _ in failed],
            )
        # Cycle-5 panel LS3 + Cycle-6 B3: tear down the out-of-process
        # watchdog with SIGTERM → SIGKILL escalation. `daemon=True`
        # would kill it at interpreter exit anyway, but leaving a
        # zombie watchdog past stop() means the /dev/shm segment we
        # unlink next could be held by the still-alive subprocess —
        # the unlink marks it for deletion but the fd stays bound
        # until the last holder closes, producing a stale segment
        # visible in `ls /dev/shm` until the watchdog dies.
        if self._watchdog_proc is not None:
            try:
                self._watchdog_proc.terminate()
                self._watchdog_proc.join(timeout=2.0)
                if self._watchdog_proc.is_alive():
                    logger.warning(
                        "watchdog_subprocess_ignored_sigterm_escalating_to_sigkill",
                        pid=self._watchdog_proc.pid,
                    )
                    self._watchdog_proc.kill()
                    self._watchdog_proc.join(timeout=0.5)
                    if self._watchdog_proc.is_alive():
                        logger.error(
                            "watchdog_subprocess_survived_sigkill",
                            pid=self._watchdog_proc.pid,
                        )
            except Exception:  # pragma: no cover — defensive
                logger.exception("watchdog_subprocess_shutdown_failed")
            self._watchdog_proc = None
        if self._watchdog_shmem is not None:
            try:
                self._watchdog_shmem.close()
                self._watchdog_shmem.unlink()
            except Exception:
                pass
            self._watchdog_shmem = None

    def _publish_playback_snapshot(self) -> None:
        """Publish one playback_snapshot per tick + reset frame-local artifacts.

        Cycle-1 panel UF-8 + cycle-3 panel 3C-N2: deep-copy the snapshot
        at the publication boundary so nodes can't poison the
        PlaybackContext authored cache through nested-dict aliasing.
        Cycle-1 panel SF-3: explicitly reset frame-local artifacts so a
        prior tick's values can't leak via a node's fallback logic.
        Cycle-2 panel NC-8: use `_snapshot_internal_locked` so we pay
        for exactly ONE deep-copy per tick (the public `snapshot()` would
        cost two).
        """
        playback = get_shared_playback_context()
        if playback is None:
            self._state["playback_snapshot"] = {}
        else:
            with playback._lock:
                aliased = playback._snapshot_internal_locked()
            self._state["playback_snapshot"] = copy.deepcopy(aliased)
        self._state["preposition_targets"] = []
        self._state["surface_layers"] = []
        self._state["laser_zone_rules"] = {}
        self._state["trigger_events"] = []

    def step(self) -> PhotonicState:
        """Execute one iteration of the graph."""
        with self._state_lock:
            self._sync_control_state()
            self._sync_output_blackout_latches()
            self._publish_playback_snapshot()
            self._state = self.graph.invoke(self._state)
            if self.control_plane_service is not None:
                node_stats = {
                    name: node.get_stats()
                    for name, node in self.nodes.items()
                    if hasattr(node, "get_stats")
                }
                self.control_plane_service.update_from_photonic_state(
                    self._state,
                    node_stats=node_stats,
                )
            # Cycle-5 panel LS3: write heartbeat to shmem so the
            # out-of-process watchdog knows the graph is alive. If
            # this stops advancing, the watchdog escalates to
            # SIGUSR1 (soft) then SIGKILL (hard). Writing heartbeat
            # last so a partial-tick stall is still detected.
            self._tick_number += 1
            if self._watchdog_shmem is not None:
                try:
                    dmx_frames = 0
                    ilda_frames = 0
                    dmx_node = self.nodes.get("dmx_output")
                    if dmx_node is not None and hasattr(dmx_node, "get_stats"):
                        stats = dmx_node.get_stats()
                        dmx_frames = int(stats.get("frames_sent", 0))
                    ilda_node = self.nodes.get("ilda_transport")
                    if ilda_node is not None and hasattr(ilda_node, "get_stats"):
                        stats = ilda_node.get_stats()
                        ilda_frames = int(stats.get("hardware_frames_sent", stats.get("frames_sent", 0)))
                    self._watchdog_shmem.write_main(
                        main_heartbeat=self._tick_number,
                        tick_number=self._tick_number,
                        dmx_frames_sent=dmx_frames,
                        ilda_frames_sent=ilda_frames,
                    )
                except Exception:
                    # Shmem write MUST NOT block the tick. If anything
                    # goes wrong (segment gone, write fails), silently
                    # continue — the watchdog will detect the missing
                    # heartbeat and escalate.
                    pass
            return self._state

    def _sync_control_state(self) -> None:
        if self.control_plane_service is None:
            return
        self._state["control_state"].update(
            self.control_plane_service.consume_control_snapshot_for_graph(),
        )

    def _sync_output_blackout_latches(self) -> None:
        control_state = self._state["control_state"]
        safety_state = self._state["safety_state"]
        should_blackout = bool(
            not control_state["armed_live"]
            or control_state["blackout_active"]
            or safety_state["emergency_stop"]
        )

        for output_name in ("dmx_output", "ilda_output", "ilda_transport"):
            output = self.nodes.get(output_name)
            if output is None:
                continue
            if should_blackout:
                if hasattr(output, "request_blackout"):
                    output.request_blackout()
            elif hasattr(output, "clear_blackout_request"):
                output.clear_blackout_request()

    def run_loop(self, target_fps: float = 50.0) -> None:
        """Run the graph in a continuous loop at target FPS."""
        import time

        frame_time = 1.0 / target_fps
        if self.dual_loop:
            logger.warning(
                "Dual-loop runtime flag is enabled, but single-loop execution path is active",
            )

        # Cycle-5 LOW (Review 1): slow-frame telemetry. Previously frame
        # overruns only logged under `settings.debug`, which means
        # production post-crash logs tell oncall nothing about WHICH
        # node missed its budget. Emit a rate-limited production log
        # with the top-N per-node processing_times so the 3 a.m.
        # debugging hole has a floor.
        _OVERRUN_LOG_INTERVAL_S = 5.0
        _last_overrun_log = 0.0
        _overruns_since_last_log = 0

        try:
            self.start()
            while self._running:
                start = time.perf_counter()
                self.step()
                elapsed = time.perf_counter() - start

                # Sleep to maintain target FPS
                sleep_time = frame_time - elapsed
                if sleep_time > 0:
                    if self.hybrid_pacing:
                        self._sleep_with_hybrid_pacing(sleep_time)
                    else:
                        time.sleep(sleep_time)
                else:
                    _overruns_since_last_log += 1
                    now = time.monotonic()
                    if now - _last_overrun_log >= _OVERRUN_LOG_INTERVAL_S:
                        # Build the top-N per-node timing table so
                        # oncall can see which node is over budget
                        # WITHOUT digging into the live-state API.
                        pt = self._state.get("processing_times", {}) or {}
                        top = sorted(
                            pt.items(), key=lambda kv: kv[1] if isinstance(kv[1], (int, float)) else 0.0,
                            reverse=True,
                        )[:5]
                        top_ms = [
                            (name, round(t * 1000, 2))
                            for name, t in top
                            if isinstance(t, (int, float))
                        ]
                        logger.warning(
                            "frame_overrun",
                            elapsed_ms=round(elapsed * 1000, 2),
                            target_ms=round(frame_time * 1000, 2),
                            overruns_since_last_log=_overruns_since_last_log,
                            top_node_times_ms=top_ms,
                        )
                        _last_overrun_log = now
                        _overruns_since_last_log = 0
                    elif self.settings.debug:
                        # Debug mode still emits every overrun for fine-grained tracing.
                        logger.warning(
                            "Frame overrun",
                            elapsed_ms=elapsed * 1000,
                            target_ms=frame_time * 1000,
                        )
        finally:
            self.stop()

    @staticmethod
    def _sleep_with_hybrid_pacing(sleep_time: float) -> None:
        """
        Use coarse sleep plus a short spin/yield tail for tighter frame pacing.
        """
        import time

        if sleep_time <= 0:
            return
        deadline = time.perf_counter() + sleep_time
        coarse = sleep_time - 0.002
        if coarse > 0:
            time.sleep(coarse)
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                break
            if remaining > 0.0005:
                time.sleep(0)

    @property
    def state(self) -> PhotonicState:
        """Get current state."""
        with self._state_lock:
            return self._state


def build_photonic_graph(
    settings: Settings | None = None,
    mock_sensors: bool = False,
    control_plane_service: ControlPlaneStateService | None = None,
    node_overrides: dict[str, Any] | None = None,
) -> PhotonicGraph:
    """
    Build and compile the complete photonic synesthesia graph.

    Args:
        settings: Configuration settings. Uses defaults if None.
        mock_sensors: If True, use mock sensor nodes for testing.
        node_overrides: Optional node implementations keyed by graph node name.

    Returns:
        Compiled PhotonicGraph ready for execution.
    """
    if settings is None:
        settings = Settings()

    logger.info("Building photonic graph", mock_sensors=mock_sensors)

    # Initialize nodes
    nodes: dict[str, Any] = {}

    if mock_sensors:
        from photonic_synesthesia.graph.nodes.mocks import (
            MockAudioSenseNode,
            MockCVSenseNode,
            MockDMXOutputNode,
            MockMidiSenseNode,
        )

        nodes["audio_sense"] = MockAudioSenseNode()
        nodes["midi_sense"] = MockMidiSenseNode()
        nodes["cv_sense"] = MockCVSenseNode()
        nodes["dmx_output"] = MockDMXOutputNode()
    else:
        nodes["audio_sense"] = AudioSenseNode(settings.audio)
        nodes["midi_sense"] = MidiSenseNode(settings.midi)
        nodes["cv_sense"] = CVSenseNode(
            settings.cv,
            cv_threaded=settings.runtime_flags.cv_threaded,
        )
        nodes["dmx_output"] = DMXOutputNode(
            settings.dmx,
            dmx_double_buffer=settings.runtime_flags.dmx_double_buffer,
        )

    # Analysis nodes (always real)
    nodes["feature_extract"] = FeatureExtractNode(
        streaming_dsp=settings.runtime_flags.streaming_dsp
    )
    nodes["beat_track"] = BeatTrackNode(settings.beat_tracking)
    nodes["structure_detect"] = StructureDetectNode(settings.structure_detection)
    nodes["fusion"] = FusionNode()
    nodes["director_intent"] = DirectorIntentNode()
    nodes["scene_select"] = SceneSelectNode(settings.scene)

    # Fixture control nodes
    nodes["laser_control"] = LaserControlNode(
        settings.fixtures,
        settings.safety.laser,
        fixtures_dir=settings.fixtures_dir,
    )
    nodes["moving_head_control"] = MovingHeadControlNode(
        settings.fixtures, settings.safety.moving_head
    )
    nodes["panel_control"] = PanelControlNode(settings.fixtures)
    nodes["interpreter"] = InterpreterNode(settings.safety)
    nodes["ilda_output"] = ILDAOutputNode(
        settings.ilda,
        settings.fixtures,
        settings.safety.laser,
        fixtures_dir=settings.fixtures_dir,
    )
    nodes["ilda_transport"] = ILDADACOutputNode(
        settings.ilda,
        settings.safety.laser,
        settings.fixtures,
    )
    # Cycle-5 HIGH (LS1 variant): post-interlock exporter. Wired AFTER
    # `laser_vector_interlock` in the pipeline below so exported
    # `.ild`/`.json` artifacts reflect the clamped frames the DAC
    # actually transmitted, not the pre-clamp frames ILDAOutputNode
    # produced upstream.
    nodes["ilda_export"] = ILDAExportNode(settings.ilda)

    # Safety node. require_watchdog=True fails loudly if the dead-man
    # switch couldn't be installed (e.g., no outputs wired in the
    # settings).
    nodes["safety_interlock"] = SafetyInterlockNode(
        settings.safety,
        settings.fixtures,
        dmx_output=nodes["dmx_output"],
        ilda_output=nodes["ilda_transport"],
        require_watchdog=True,
    )
    safety_monitor = SafetyMonitor(
        dmx_output=nodes["dmx_output"],
        ilda_output=nodes["ilda_transport"],
        check_interval=0.1,
        max_silence=max(0.5 * settings.safety.heartbeat_timeout_s, 0.05),
    )
    nodes["laser_vector_interlock"] = LaserVectorInterlockNode(
        settings.safety.laser,
        fixtures=settings.fixtures,
    )

    # Professional rollout (Task 3) runtime nodes. Ordering: trigger_router
    # / preposition / surface_compositor land AFTER scene_select so they
    # see the active section in the published snapshot; laser_zone_runtime
    # lands AFTER ilda_output (which populates `state["laser_zone_rules"]`)
    # and BEFORE laser_vector_interlock (which validates the final frame).
    nodes["trigger_router"] = TriggerRouterNode()
    nodes["preposition"] = PrepositionNode(fixtures=settings.fixtures)
    nodes["surface_compositor"] = SurfaceCompositorNode(fixtures=settings.fixtures)
    nodes["laser_zone_runtime"] = LaserZoneRuntimeNode(fixtures=settings.fixtures)

    if node_overrides:
        nodes.update(node_overrides)

    pipeline = _SequentialPipeline(
        node_names=[
            "audio_sense",
            "feature_extract",
            "beat_track",
            "structure_detect",
            "midi_sense",
            "cv_sense",
            "fusion",
            "director_intent",
            "scene_select",
            "trigger_router",
            "preposition",
            "surface_compositor",
            "laser_control",
            "moving_head_control",
            "panel_control",
            "interpreter",
            "safety_interlock",
            "ilda_output",
            "laser_zone_runtime",
            "laser_vector_interlock",
            "ilda_export",
            "ilda_transport",
            "dmx_output",
        ],
        nodes=nodes,
    )

    return PhotonicGraph(
        pipeline,
        settings,
        nodes,
        control_plane_service=control_plane_service,
        safety_monitor=safety_monitor,
    )


def build_minimal_graph(
    settings: Settings | None = None,
    control_plane_service: ControlPlaneStateService | None = None,
) -> PhotonicGraph:
    """
    Build a minimal graph for testing DMX output only.

    Useful for fixture calibration and basic testing without
    full audio analysis.
    """
    if settings is None:
        settings = Settings()

    from photonic_synesthesia.graph.nodes.mocks import MockAudioSenseNode

    dmx_output = DMXOutputNode(
        settings.dmx,
        dmx_double_buffer=settings.runtime_flags.dmx_double_buffer,
    )
    nodes = {
        "audio_sense": MockAudioSenseNode(),
        "dmx_output": dmx_output,
        "safety_interlock": SafetyInterlockNode(
            settings.safety,
            settings.fixtures,
            dmx_output=dmx_output,
            require_watchdog=True,
        ),
    }
    safety_monitor = SafetyMonitor(
        dmx_output=dmx_output,
        check_interval=0.1,
        max_silence=max(0.5 * settings.safety.heartbeat_timeout_s, 0.05),
    )

    pipeline = _SequentialPipeline(
        node_names=[
            "audio_sense",
            "safety_interlock",
            "dmx_output",
        ],
        nodes=nodes,
    )
    return PhotonicGraph(
        pipeline,
        settings,
        nodes,
        control_plane_service=control_plane_service,
        safety_monitor=safety_monitor,
    )
