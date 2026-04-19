# Photonic Synesthesia

**AI-Driven Laser Show Controller for AlphaTheta XDJ-AZ**

An autonomous lighting control system built around a deterministic node pipeline, combining real-time audio analysis, MIDI telemetry, and computer vision to create structure-aware, music-reactive light shows.

## Overview

Photonic Synesthesia operates on a "Listener-Observer" model using air-gap technologies:

- **Audio Analysis**: Real-time spectral analysis via librosa, beat tracking via BeatNet/madmom
- **MIDI Telemetry**: Captures DJ intent from XDJ-AZ faders, filters, and pads
- **Computer Vision**: Reads BPM and waveforms from Rekordbox screen
- **DMX Control**: Outputs to lasers, moving heads, and LED panels via Enttec Open DMX USB

## Key Features

- **Structure Detection**: Automatically detects drops, buildups, and breakdowns
- **Deterministic Pipeline Runtime**: Ordered node execution with explicit safety and output stages
- **Safety Interlocks**: Multiple layers of software safety for laser operation
- **Scene System**: JSON-defined scenes with beat-synced effects
- **No Pro DJ Link Required**: Works entirely through audio loopback and MIDI

## Hardware Requirements

| Component | Requirement |
|-----------|-------------|
| DJ Controller | AlphaTheta XDJ-AZ |
| Audio Interface | USB audio interface (Scarlett, UMC, etc.) |
| DMX Interface | Enttec Open DMX USB |
| Computer | Linux/macOS, 4+ cores, 8GB+ RAM |
| Fixtures | DMX-controlled lasers, moving heads, LED panels |

## Installation

```bash
# Clone repository
git clone https://github.com/toimfortes/laser_show_xdj_az.git
cd laser_show_xdj_az

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/macOS
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -e .

# For BeatNet support (recommended)
pip install -e ".[beatnet]"

# For development
pip install -e ".[dev]"
```

## Quick Start

```bash
# List available audio devices
photonic list-audio

# List available MIDI ports
photonic list-midi

# Run with mock sensors (no hardware)
photonic run --mock

# Run with real hardware
photonic run

# Test DMX output
photonic dmx-test -c 1 -v 255  # Channel 1 to full

# Run with Pknight Art-Net + single OEM 7CH laser profile
photonic run --config config/pknight_single_laser.yaml
```

## Configuration

Edit `config/default.yaml` to configure:

- Audio device selection
- MIDI port auto-detection patterns
- DMX interface settings
- Safety limits
- Fixture definitions

### Fixture Setup

Add fixtures to `config/default.yaml`:

```yaml
fixtures:
  - id: "laser1"
    name: "Main Laser"
    type: "laser"
    profile: "laser_generic_7ch"
    start_address: 1
    enabled: true

  - id: "mover1"
    name: "Moving Head L"
    type: "moving_head"
    profile: "moving_head_16ch"
    start_address: 10
    enabled: true
```

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                Deterministic Node Pipeline          │
├─────────────────────────────────────────────────────┤
│ Audio Sense → Feature Extract → Beat Track         │
│ Structure Detect → MIDI Sense → CV Sense           │
│ Fusion → Director Intent → Scene Select            │
│ Trigger Router → Preposition → Surface Compositor   │
│ Laser / Moving Head / Panel Control                │
│ Interpreter → Safety Interlock                     │
│ ILDA Frame Build → Laser Zone Runtime              │
│   → ILDA Vector Interlock → ILDA Transport         │
│ DMX Output                                          │
└─────────────────────────────────────────────────────┘
```

The professional-rollout authored-state ownership model:

- `PlaybackContext` owns authored show data (`show_sections`,
  `timeline_flags`, `staged_look`, `operator_workspace_banks`).
- `PhotonicGraph.step()` publishes one `playback_snapshot` per tick
  via deep-copy at the publication boundary, plus an explicit reset
  of the four frame-local artifact fields (`trigger_events`,
  `preposition_targets`, `surface_layers`, `laser_zone_rules`).
- `TriggerRouterNode`, `PrepositionNode`, `SurfaceCompositorNode`,
  and the retrofitted `ILDAOutputNode` / `MovingHeadControlNode`
  all read authored state from `state["playback_snapshot"]` — never
  the global PlaybackContext mid-tick.
- `LaserZoneRuntimeNode` is a pure transform on `ilda_frames`
  (brightness clamp + per-fixture protected half-plane); it runs
  AFTER `ilda_output` (which populates `state["laser_zone_rules"]`)
  and BEFORE `laser_vector_interlock`.

Operator preview/commit staging:

- `set_staged_look()` is preview-only — surfaces in `playback_snapshot`
  for UI rendering, does not affect runtime output.
- `commit_staged_look()` deep-merges the staged overrides into the
  authored section (operator-supplied keys win; authored siblings
  survive) and clears the staged sidecar.
- The hash-derived revision counter is split: `_authored_hash` gates
  the snapshot cache; `_flags_hash` gates `_timeline_flag_revision`
  so non-flag mutations (staged_look, intent expiry, tag edits) do
  NOT clear `TriggerRouterNode`'s fire-once ledger.

## Safety

**IMPORTANT**: This system controls Class 3B/4 laser equipment. Improper use can cause permanent eye damage.

Built-in safety features:
- **Y-axis clamping**: Prevents lasers from pointing at audience
- **Minimum scan speed**: Prevents static beam burns
- **Strobe rate limiting**: Reduces seizure risk
- **Heartbeat monitoring**: Blackout if system hangs
- **Emergency stop**: Immediate blackout capability

**Always have a qualified laser safety officer present when operating Class 3B+ lasers.**

## Development

```bash
# Run tests
pytest

# Type checking
mypy src/

# Linting
ruff check src/

# Format code
black src/
```

## Project Structure

```
laser_show_xdj_az/
├── src/photonic_synesthesia/
│   ├── core/           # State, config, exceptions
│   ├── graph/          # Deterministic pipeline orchestration
│   │   └── nodes/      # Graph node implementations
│   ├── analysis/       # Audio/visual analysis
│   ├── dmx/            # DMX control layer
│   ├── scenes/         # Scene management
│   ├── safety/         # Safety systems
│   └── ui/             # CLI and web interface
├── config/
│   ├── fixtures/       # Fixture profiles
│   └── scenes/         # Scene definitions
└── tests/
```

## Research Sources

- [librosa](https://librosa.org/) - Audio analysis
- [BeatNet](https://github.com/mjhydri/BeatNet) - Real-time beat tracking
- [madmom](https://github.com/CPJKU/madmom) - Music information retrieval
- [Oculizer](https://github.com/LandryBulls/Oculizer) - Music-reactive DMX inspiration

## License

MIT License - See LICENSE file for details.

## Disclaimer

This software is provided as-is for educational and experimental purposes. The authors are not responsible for any damage to equipment, property, or persons resulting from the use of this software. Always follow local regulations regarding laser operation and obtain necessary permits/variances.
