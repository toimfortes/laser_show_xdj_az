"""
Command-Line Interface for Photonic Synesthesia.

Provides commands for running the system, testing fixtures,
and calibrating sensors.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import click
import structlog

from photonic_synesthesia import __version__

logger = structlog.get_logger()


@click.group()
@click.version_option(version=__version__)
@click.option("--debug", is_flag=True, help="Enable debug logging")
@click.option(
    "--config",
    type=click.Path(exists=True),
    help="Path to configuration file",
)
@click.pass_context
def cli(ctx: click.Context, debug: bool, config: Optional[str]) -> None:
    """
    Photonic Synesthesia - AI-Driven Laser Show Controller for XDJ-AZ

    An autonomous lighting control system that uses LangGraph for orchestration,
    combining real-time audio analysis, MIDI telemetry, and computer vision
    to create structure-aware, music-reactive light shows.
    """
    ctx.ensure_object(dict)

    # Configure logging
    log_level = "DEBUG" if debug else "INFO"
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(structlog, log_level)
        ),
    )

    ctx.obj["debug"] = debug
    ctx.obj["config_path"] = Path(config) if config else None


@cli.command()
@click.option("--mock", is_flag=True, help="Use mock sensors (no hardware)")
@click.option("--fps", default=50.0, help="Target frames per second")
@click.pass_context
def run(ctx: click.Context, mock: bool, fps: float) -> None:
    """Run the photonic synesthesia system."""
    from photonic_synesthesia.core.config import Settings
    from photonic_synesthesia.graph import build_photonic_graph

    click.echo(f"Photonic Synesthesia v{__version__}")
    click.echo("=" * 50)

    # Load config
    if ctx.obj["config_path"]:
        settings = Settings.from_yaml(ctx.obj["config_path"])
    else:
        settings = Settings()

    settings.debug = ctx.obj["debug"]

    click.echo(f"Mode: {'Mock' if mock else 'Live'}")
    click.echo(f"Target FPS: {fps}")
    click.echo()

    # Build and run graph
    try:
        graph = build_photonic_graph(settings, mock_sensors=mock)
        click.echo("Graph built successfully. Starting...")
        click.echo("Press Ctrl+C to stop.")
        click.echo()

        graph.run_loop(target_fps=fps)

    except KeyboardInterrupt:
        click.echo("\nShutting down...")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        if ctx.obj["debug"]:
            raise
        sys.exit(1)


@cli.command()
@click.option("--channel", "-c", type=int, required=True, help="DMX channel (1-512)")
@click.option("--value", "-v", type=int, required=True, help="Value (0-255)")
@click.pass_context
def dmx_test(ctx: click.Context, channel: int, value: int) -> None:
    """Test DMX output by setting a single channel."""
    from photonic_synesthesia.core.config import Settings
    from photonic_synesthesia.graph.nodes.dmx_output import DMXOutputNode

    if not 1 <= channel <= 512:
        click.echo("Error: Channel must be 1-512", err=True)
        sys.exit(1)

    if not 0 <= value <= 255:
        click.echo("Error: Value must be 0-255", err=True)
        sys.exit(1)

    settings = Settings()
    dmx = DMXOutputNode(settings.dmx)

    click.echo(f"Setting channel {channel} to {value}...")

    try:
        dmx.start()
        dmx.set_channel(channel, value)
        click.echo("Press Ctrl+C to stop and blackout.")

        import time
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        click.echo("\nBlacking out...")
        dmx.blackout()
        dmx.stop()


@cli.command()
@click.pass_context
def list_audio(ctx: click.Context) -> None:
    """List available audio input devices."""
    try:
        import sounddevice as sd
        devices = sd.query_devices()

        click.echo("Available audio devices:")
        click.echo("-" * 60)

        for i, device in enumerate(devices):
            if device["max_input_channels"] > 0:
                marker = " *" if i == sd.default.device[0] else "  "
                click.echo(f"{marker} [{i}] {device['name']}")
                click.echo(f"      Channels: {device['max_input_channels']}")
                click.echo(f"      Sample Rate: {device['default_samplerate']}")

    except ImportError:
        click.echo("Error: sounddevice not installed", err=True)
        sys.exit(1)


@cli.command()
@click.pass_context
def list_midi(ctx: click.Context) -> None:
    """List available MIDI input ports."""
    try:
        import mido
        ports = mido.get_input_names()

        click.echo("Available MIDI input ports:")
        click.echo("-" * 60)

        for port in ports:
            click.echo(f"  {port}")

        if not ports:
            click.echo("  (no MIDI ports found)")

    except ImportError:
        click.echo("Error: mido not installed", err=True)
        sys.exit(1)


@cli.command()
@click.option("--duration", "-d", default=10.0, help="Analysis duration in seconds")
@click.pass_context
def analyze(ctx: click.Context, duration: float) -> None:
    """Run audio analysis and display detected features."""
    import time
    from photonic_synesthesia.core.config import Settings
    from photonic_synesthesia.core.state import create_initial_state
    from photonic_synesthesia.graph.nodes.audio_sense import AudioSenseNode
    from photonic_synesthesia.graph.nodes.feature_extract import FeatureExtractNode
    from photonic_synesthesia.graph.nodes.beat_track import BeatTrackNode
    from photonic_synesthesia.graph.nodes.structure_detect import StructureDetectNode

    settings = Settings()
    state = create_initial_state()

    # Initialize nodes
    audio = AudioSenseNode(settings.audio)
    features = FeatureExtractNode()
    beats = BeatTrackNode(settings.beat_tracking)
    structure = StructureDetectNode(settings.structure_detection)

    click.echo(f"Analyzing audio for {duration} seconds...")
    click.echo("Press Ctrl+C to stop early.")
    click.echo()

    try:
        audio.start()
        start_time = time.time()

        while time.time() - start_time < duration:
            # Run analysis pipeline
            state = audio(state)
            state = features(state)
            state = beats(state)
            state = structure(state)

            # Display results
            af = state["audio_features"]
            bi = state["beat_info"]

            click.echo(
                f"\rBPM: {bi['bpm']:6.1f} | "
                f"Energy: {af['rms_energy']:5.3f} | "
                f"Structure: {state['current_structure'].value:12s} | "
                f"Drop Prob: {state['drop_probability']:4.2f}",
                nl=False,
            )

            time.sleep(0.05)

    except KeyboardInterrupt:
        pass
    finally:
        audio.stop()
        click.echo()


def main() -> None:
    """Entry point for the CLI."""
    cli(obj={})


if __name__ == "__main__":
    main()
