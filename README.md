# Photonic Synesthesia

**AI-Driven Laser Show Controller for AlphaTheta XDJ-AZ**

An autonomous lighting control system that uses LangGraph for orchestration, combining real-time audio analysis, MIDI telemetry, and computer vision to create structure-aware, music-reactive light shows.

## Overview

Photonic Synesthesia operates on a "Listener-Observer" model using air-gap technologies:

- **Audio Analysis**: Real-time spectral analysis via librosa, beat tracking via BeatNet/madmom
- **MIDI Telemetry**: Captures DJ intent from XDJ-AZ faders, filters, and pads
- **Computer Vision**: Reads BPM and waveforms from Rekordbox screen
- **DMX Control**: Outputs to lasers, moving heads, and LED panels via Enttec Open DMX USB

## Key Features

- **Structure Detection**: Automatically detects drops, buildups, and breakdowns
- **LangGraph Orchestration**: Modular state machine with parallel sensor processing
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
│                  LangGraph State Machine             │
├─────────────────────────────────────────────────────┤
│  Audio Sense → Feature Extract → Beat Track →       │
│      ↓              ↓              ↓                │
│  MIDI Sense  ────→ Fusion ←──── CV Sense           │
│                      ↓                               │
│              Scene Selection                         │
│                      ↓                               │
│  Laser Ctrl   Moving Head Ctrl   Panel Ctrl        │
│       ↓              ↓              ↓               │
│              DMX Output                              │
│                  ↓                                   │
│          Safety Interlock                            │
└─────────────────────────────────────────────────────┘
```

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
│   ├── graph/          # LangGraph orchestration
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

- [LangGraph](https://github.com/langchain-ai/langgraph) - State machine orchestration
- [librosa](https://librosa.org/) - Audio analysis
- [BeatNet](https://github.com/mjhydri/BeatNet) - Real-time beat tracking
- [madmom](https://github.com/CPJKU/madmom) - Music information retrieval
- [Oculizer](https://github.com/LandryBulls/Oculizer) - Music-reactive DMX inspiration

## License

MIT License - See LICENSE file for details.

## Disclaimer

This software is provided as-is for educational and experimental purposes. The authors are not responsible for any damage to equipment, property, or persons resulting from the use of this software. Always follow local regulations regarding laser operation and obtain necessary permits/variances.
