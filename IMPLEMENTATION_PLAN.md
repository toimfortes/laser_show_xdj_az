# AI-Driven Laser Show Controller for XDJ-AZ

## Autonomous Photonic Synesthesia: LangGraph-Based Implementation

### Executive Summary

This document outlines a robust implementation plan for an AI-driven lighting control system for the AlphaTheta XDJ-AZ, using **LangGraph** as the orchestration framework. The system operates on a "Listener-Observer" model with air-gap technologies, leveraging MIDI telemetry, real-time audio analysis, and computer vision to create structure-aware lighting automation.

---

## 1. System Architecture Overview

### 1.1 LangGraph State Machine Design

The system uses LangGraph to model the lighting control workflow as a directed graph with stateful nodes:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         LANGGRAPH ORCHESTRATOR                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                   │
│  │ AUDIO_SENSE  │───▶│ FEATURE_     │───▶│ STRUCTURE_   │                   │
│  │    NODE      │    │ EXTRACT_NODE │    │ DETECT_NODE  │                   │
│  └──────────────┘    └──────────────┘    └──────────────┘                   │
│         │                   │                   │                            │
│         ▼                   ▼                   ▼                            │
│  ┌──────────────────────────────────────────────────────┐                   │
│  │              FUSION_NODE (State Aggregator)          │                   │
│  └──────────────────────────────────────────────────────┘                   │
│         │                   │                   │                            │
│  ┌──────┴───────┐   ┌──────┴───────┐   ┌──────┴───────┐                     │
│  │  MIDI_SENSE  │   │  CV_SENSE    │   │  INTENT_     │                     │
│  │    NODE      │   │    NODE      │   │  PREDICT_NODE│                     │
│  └──────────────┘   └──────────────┘   └──────────────┘                     │
│                              │                                               │
│                              ▼                                               │
│  ┌──────────────────────────────────────────────────────┐                   │
│  │           SCENE_SELECT_NODE (AI Decision)            │                   │
│  └──────────────────────────────────────────────────────┘                   │
│                              │                                               │
│         ┌────────────────────┼────────────────────┐                         │
│         ▼                    ▼                    ▼                         │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                   │
│  │ LASER_CTRL   │    │ MOVING_HEAD  │    │ PANEL_CTRL   │                   │
│  │    NODE      │    │ _CTRL_NODE   │    │    NODE      │                   │
│  └──────────────┘    └──────────────┘    └──────────────┘                   │
│         │                    │                    │                         │
│         └────────────────────┼────────────────────┘                         │
│                              ▼                                               │
│  ┌──────────────────────────────────────────────────────┐                   │
│  │              DMX_OUTPUT_NODE (Thread-Safe)           │                   │
│  └──────────────────────────────────────────────────────┘                   │
│                              │                                               │
│                              ▼                                               │
│  ┌──────────────────────────────────────────────────────┐                   │
│  │           SAFETY_INTERLOCK_NODE (Always Active)      │                   │
│  └──────────────────────────────────────────────────────┘                   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 Core Design Principles

| Principle | Implementation |
|-----------|----------------|
| **Air-Gap Operation** | No Pro DJ Link dependency; uses audio loopback + MIDI + CV |
| **Thread Isolation** | DMX transmission on dedicated high-priority thread |
| **Graceful Degradation** | System continues with reduced features if sensors fail |
| **Safety-First** | Hardware interlocks + software limits on laser positioning |
| **Modular Scenes** | JSON-defined scenes with fixture profiles |

---

## 2. Hardware Architecture

### 2.1 Signal Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              XDJ-AZ                                          │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐              │
│  │   Master 2 Out  │  │   USB-C MIDI    │  │   Display Out   │              │
│  │     (RCA)       │  │   (CC/Note)     │  │   (to Laptop)   │              │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘              │
└───────────┼─────────────────────┼─────────────────────┼──────────────────────┘
            │                     │                     │
            ▼                     ▼                     ▼
┌───────────────────┐  ┌───────────────────┐  ┌───────────────────┐
│  USB Audio I/F    │  │  USB MIDI Input   │  │  Screen Capture   │
│  (Scarlett/UMC)   │  │  (Class Compliant)│  │  (mss + OpenCV)   │
│  48kHz/24-bit     │  │                   │  │  BPM ROI + Wave   │
└─────────┬─────────┘  └─────────┬─────────┘  └─────────┬─────────┘
          │                      │                      │
          └──────────────────────┼──────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        CONTROL COMPUTER (Python Host)                        │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                      LangGraph State Machine                            ││
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐       ││
│  │  │AudioAnalysis│ │  BeatNet    │ │  MIDI Proc  │ │  CV/OCR     │       ││
│  │  │  (librosa)  │ │  (RNN+PF)   │ │  (mido)     │ │  (OpenCV)   │       ││
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘       ││
│  │                           │                                             ││
│  │                           ▼                                             ││
│  │  ┌─────────────────────────────────────────────────────────────────────┐││
│  │  │                    Scene Engine + Fixture Mapper                    │││
│  │  └─────────────────────────────────────────────────────────────────────┘││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                 │                                            │
│                                 ▼                                            │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │              DMX Thread (pyftdi) → Enttec Open DMX USB                  ││
│  └─────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           DMX512 UNIVERSE                                    │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐ │
│  │ Laser (1-15)  │  │ Moving Head 1 │  │ Moving Head 2 │  │  LED Panels   │ │
│  │ 7-15 channels │  │ (16-31) 16ch  │  │ (32-47) 16ch  │  │ (48-63) 16ch  │ │
│  └───────────────┘  └───────────────┘  └───────────────┘  └───────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Hardware Requirements

| Component | Specification | Purpose |
|-----------|---------------|---------|
| **XDJ-AZ** | AlphaTheta all-in-one | Audio source + MIDI telemetry |
| **USB Audio Interface** | Focusrite Scarlett / Behringer UMC | Audio capture (Master 2 → Line In) |
| **USB-DMX Interface** | Enttec Open DMX USB | DMX512 output (requires pyftdi) |
| **Control Computer** | Linux/macOS, 4+ cores, 8GB+ RAM | Processing host |
| **Laser Projector(s)** | DMX-controlled, 7-15 channels | Beam effects |
| **Moving Head(s)** | DMX-controlled, 11-19 channels | Kinetic lighting |
| **LED Panels** | DMX-controlled, RGB/RGBW | Wash/ambient lighting |

---

## 3. Software Architecture

### 3.1 Project Structure

```
laser_show_xdj_az/
├── pyproject.toml                 # Project dependencies & metadata
├── README.md                      # Project documentation
├── IMPLEMENTATION_PLAN.md         # This document
│
├── src/
│   └── photonic_synesthesia/
│       ├── __init__.py
│       │
│       ├── core/                  # Core system components
│       │   ├── __init__.py
│       │   ├── config.py          # Configuration management
│       │   ├── state.py           # LangGraph state definitions
│       │   └── exceptions.py      # Custom exceptions
│       │
│       ├── graph/                 # LangGraph orchestration
│       │   ├── __init__.py
│       │   ├── nodes/             # Graph node implementations
│       │   │   ├── __init__.py
│       │   │   ├── audio_sense.py      # Audio capture node
│       │   │   ├── feature_extract.py  # Feature extraction node
│       │   │   ├── structure_detect.py # Drop/buildup detection
│       │   │   ├── midi_sense.py       # MIDI input processing
│       │   │   ├── cv_sense.py         # Computer vision node
│       │   │   ├── fusion.py           # Multi-modal fusion
│       │   │   ├── scene_select.py     # AI scene selection
│       │   │   ├── fixture_control.py  # Fixture-specific control
│       │   │   ├── dmx_output.py       # DMX transmission
│       │   │   └── safety_interlock.py # Safety systems
│       │   │
│       │   ├── edges.py           # Conditional edge functions
│       │   └── builder.py         # Graph construction
│       │
│       ├── analysis/              # Audio/visual analysis
│       │   ├── __init__.py
│       │   ├── audio/
│       │   │   ├── __init__.py
│       │   │   ├── capture.py     # Real-time audio capture
│       │   │   ├── features.py    # librosa feature extraction
│       │   │   ├── beat_tracker.py # BeatNet/madmom integration
│       │   │   └── structure.py   # Drop/buildup detection
│       │   │
│       │   └── vision/
│       │       ├── __init__.py
│       │       ├── screen_capture.py  # mss screen capture
│       │       ├── bpm_ocr.py         # BPM digit recognition
│       │       └── waveform_reader.py # Waveform color analysis
│       │
│       ├── midi/                  # MIDI processing
│       │   ├── __init__.py
│       │   ├── receiver.py        # MIDI input handling
│       │   ├── mappings.py        # XDJ-AZ MIDI mappings
│       │   └── intent.py          # DJ intent inference
│       │
│       ├── dmx/                   # DMX control layer
│       │   ├── __init__.py
│       │   ├── interface.py       # Enttec Open DMX driver
│       │   ├── universe.py        # DMX universe management
│       │   ├── fixtures/
│       │   │   ├── __init__.py
│       │   │   ├── base.py        # Base fixture class
│       │   │   ├── laser.py       # Laser fixture profiles
│       │   │   ├── moving_head.py # Moving head profiles
│       │   │   └── panel.py       # LED panel profiles
│       │   └── effects/
│       │       ├── __init__.py
│       │       ├── strobe.py      # Strobe effects
│       │       ├── chase.py       # Chase patterns
│       │       └── movement.py    # Movement generators (Lissajous, etc.)
│       │
│       ├── scenes/                # Scene management
│       │   ├── __init__.py
│       │   ├── loader.py          # JSON scene loader
│       │   ├── manager.py         # Scene state machine
│       │   └── transitions.py     # Scene transition logic
│       │
│       ├── safety/                # Safety systems
│       │   ├── __init__.py
│       │   ├── interlocks.py      # Software interlocks
│       │   ├── limits.py          # Position/intensity limits
│       │   └── watchdog.py        # System health monitoring
│       │
│       └── ui/                    # User interface (optional)
│           ├── __init__.py
│           ├── web_panel.py       # Flask/FastAPI control panel
│           └── cli.py             # Command-line interface
│
├── config/                        # Configuration files
│   ├── default.yaml               # Default system config
│   ├── fixtures/                  # Fixture profile definitions
│   │   ├── laser_generic_7ch.yaml
│   │   ├── moving_head_16ch.yaml
│   │   └── led_panel_rgb.yaml
│   └── scenes/                    # Scene definitions
│       ├── intro.json
│       ├── buildup.json
│       ├── drop.json
│       └── breakdown.json
│
├── tests/                         # Test suite
│   ├── __init__.py
│   ├── unit/
│   ├── integration/
│   └── fixtures/                  # Test fixtures/mocks
│
└── scripts/                       # Utility scripts
    ├── calibrate_fixtures.py      # DMX fixture calibration
    ├── test_dmx_output.py         # DMX connectivity test
    ├── capture_bpm_roi.py         # BPM region capture helper
    └── train_scene_clusters.py    # ML scene clustering
```

### 3.2 LangGraph State Definition

```python
from typing import TypedDict, Optional, List
from dataclasses import dataclass
from enum import Enum

class MusicStructure(Enum):
    INTRO = "intro"
    VERSE = "verse"
    BUILDUP = "buildup"
    DROP = "drop"
    BREAKDOWN = "breakdown"
    OUTRO = "outro"

class FixtureCommand(TypedDict):
    fixture_id: str
    channel_values: dict[int, int]  # channel -> value (0-255)

class PhotonicState(TypedDict):
    """Central state object flowing through LangGraph"""

    # Timing & Sync
    current_bpm: float
    beat_phase: float                    # 0.0 - 1.0 within beat
    bar_position: int                    # 1-4 within bar
    beat_confidence: float               # 0.0 - 1.0

    # Audio Features
    rms_energy: float                    # Current RMS level
    spectral_centroid: float             # Brightness indicator
    spectral_flux: float                 # Rate of spectral change
    low_energy: float                    # Sub-bass energy (20-100Hz)
    mid_energy: float                    # Mid-range energy
    high_energy: float                   # High-freq energy
    mfcc_vector: List[float]             # Timbral fingerprint

    # Structure Detection
    current_structure: MusicStructure
    structure_confidence: float
    drop_probability: float              # Imminent drop likelihood
    time_since_last_drop: float          # Seconds

    # MIDI Intent
    crossfader_position: float           # -1.0 (left) to 1.0 (right)
    channel_faders: List[float]          # 4 channels, 0.0 - 1.0
    filter_positions: List[float]        # HPF/LPF positions
    active_effects: List[str]            # Currently engaged FX
    pad_triggers: List[int]              # Recently hit pads

    # CV Data (from Rekordbox screen)
    cv_bpm: Optional[float]              # OCR-detected BPM
    lookahead_bass: float                # Predicted bass intensity
    lookahead_mids: float                # Predicted mid intensity
    lookahead_highs: float               # Predicted high intensity

    # Scene Management
    current_scene: str
    pending_scene: Optional[str]
    scene_transition_progress: float     # 0.0 - 1.0

    # DMX Output
    fixture_commands: List[FixtureCommand]
    dmx_universe: bytes                  # 512-byte buffer

    # Safety
    safety_ok: bool
    last_heartbeat: float
    error_state: Optional[str]
```

### 3.3 LangGraph Node Specifications

#### Node: `audio_sense`
**Purpose**: Capture real-time audio from USB interface
**Input**: Raw audio stream via sounddevice
**Output**: Updates `PhotonicState` with raw audio buffer
**Threading**: Runs callback in dedicated audio thread
**Library**: `sounddevice` with low-latency WASAPI/CoreAudio

```python
# Key implementation pattern
import sounddevice as sd
import numpy as np
from collections import deque

class AudioSenseNode:
    def __init__(self, sample_rate=48000, block_size=1024):
        self.buffer = deque(maxlen=int(sample_rate * 2))  # 2-second buffer
        self.stream = sd.InputStream(
            samplerate=sample_rate,
            blocksize=block_size,
            channels=2,
            dtype=np.float32,
            callback=self._audio_callback,
            latency='low'
        )

    def _audio_callback(self, indata, frames, time, status):
        # Convert stereo to mono, append to ring buffer
        mono = np.mean(indata, axis=1)
        self.buffer.extend(mono)
```

#### Node: `feature_extract`
**Purpose**: Extract spectral and rhythmic features
**Input**: Audio buffer from `audio_sense`
**Output**: RMS, spectral centroid, flux, band energies, MFCCs
**Library**: `librosa` (STFT-based features)

```python
import librosa
import numpy as np

class FeatureExtractNode:
    def __call__(self, state: PhotonicState) -> PhotonicState:
        audio = np.array(state['audio_buffer'])
        sr = state['sample_rate']

        # Compute features
        state['rms_energy'] = float(librosa.feature.rms(y=audio).mean())
        state['spectral_centroid'] = float(
            librosa.feature.spectral_centroid(y=audio, sr=sr).mean()
        )

        # Band energies via mel filterbank
        mel = librosa.feature.melspectrogram(y=audio, sr=sr, n_mels=128)
        state['low_energy'] = float(mel[:10].mean())    # ~20-200Hz
        state['mid_energy'] = float(mel[10:60].mean())  # ~200-2kHz
        state['high_energy'] = float(mel[60:].mean())   # ~2kHz+

        # MFCCs for timbral analysis
        mfcc = librosa.feature.mfcc(y=audio, sr=sr, n_mfcc=13)
        state['mfcc_vector'] = mfcc.mean(axis=1).tolist()

        return state
```

#### Node: `beat_track`
**Purpose**: Real-time beat and downbeat tracking
**Input**: Audio buffer
**Output**: BPM, beat phase, bar position, confidence
**Library**: `BeatNet` (preferred) or `madmom` with online mode

```python
from BeatNet.BeatNet import BeatNet

class BeatTrackNode:
    def __init__(self):
        # Mode 1: streaming from mic, Mode 2: real-time file
        self.estimator = BeatNet(
            1,  # Streaming mode
            mode='online',
            inference_model='PF',  # Particle filtering
            plot=[],
            thread=False
        )

    def __call__(self, state: PhotonicState) -> PhotonicState:
        output = self.estimator.process(state['audio_buffer'])
        if output is not None:
            beat_time, downbeat = output
            state['current_bpm'] = self.estimator.tempo
            state['beat_phase'] = (time.time() % (60/state['current_bpm'])) / (60/state['current_bpm'])
            state['bar_position'] = 1 if downbeat else state.get('bar_position', 1)
        return state
```

#### Node: `structure_detect`
**Purpose**: Detect musical structure (drop, buildup, breakdown)
**Input**: Audio features + historical buffer
**Output**: Current structure classification, drop probability

```python
class StructureDetectNode:
    def __init__(self):
        self.rms_history = deque(maxlen=500)  # ~10 seconds at 50Hz
        self.last_drop_time = 0

    def __call__(self, state: PhotonicState) -> PhotonicState:
        self.rms_history.append(state['rms_energy'])

        # Buildup detection: rising RMS + high spectral centroid
        recent_rms = list(self.rms_history)[-100:]  # Last 2 seconds
        rms_slope = np.polyfit(range(len(recent_rms)), recent_rms, 1)[0]

        # Drop detection heuristic
        long_term_avg = np.mean(list(self.rms_history))
        current_rms = state['rms_energy']

        # Pre-drop gap: sudden silence after buildup
        is_gap = current_rms < (long_term_avg * 0.3)

        # Drop: high energy spike dominated by bass
        is_drop = (
            current_rms > (long_term_avg * 2.0) and
            state['low_energy'] > state['mid_energy'] and
            time.time() - self.last_drop_time > 10  # Debounce
        )

        if is_drop:
            state['current_structure'] = MusicStructure.DROP
            state['drop_probability'] = 0.0
            self.last_drop_time = time.time()
        elif rms_slope > 0.01 and state['spectral_centroid'] > 3000:
            state['current_structure'] = MusicStructure.BUILDUP
            state['drop_probability'] = min(1.0, rms_slope * 10)
        elif is_gap:
            state['drop_probability'] = 0.95  # Drop imminent
        elif state['low_energy'] < 0.1:
            state['current_structure'] = MusicStructure.BREAKDOWN
            state['drop_probability'] = 0.0

        return state
```

#### Node: `midi_sense`
**Purpose**: Process XDJ-AZ MIDI messages for DJ intent
**Input**: MIDI CC/Note messages via USB
**Output**: Fader positions, FX states, pad triggers
**Library**: `mido` with `python-rtmidi` backend

```python
import mido

class MidiSenseNode:
    # XDJ-AZ MIDI CC mappings (approximate - verify with manual)
    CROSSFADER_CC = 0x0F
    CHANNEL_FADER_CC = [0x13, 0x14, 0x15, 0x16]  # Ch 1-4
    FILTER_CC = [0x17, 0x18, 0x19, 0x1A]         # Ch 1-4 filter

    def __init__(self, port_name='XDJ-AZ'):
        self.port = mido.open_input(port_name, callback=self._on_message)
        self.state_updates = queue.Queue()

    def _on_message(self, msg):
        if msg.type == 'control_change':
            self.state_updates.put(('cc', msg.control, msg.value))
        elif msg.type == 'note_on':
            self.state_updates.put(('pad', msg.note, msg.velocity))

    def __call__(self, state: PhotonicState) -> PhotonicState:
        while not self.state_updates.empty():
            msg_type, param, value = self.state_updates.get_nowait()
            if msg_type == 'cc':
                if param == self.CROSSFADER_CC:
                    state['crossfader_position'] = (value / 127.0) * 2 - 1
                # ... handle other CCs
            elif msg_type == 'pad':
                state['pad_triggers'].append(param)
        return state
```

#### Node: `cv_sense`
**Purpose**: Read BPM and waveform from Rekordbox screen
**Input**: Screen capture of defined ROI
**Output**: CV-detected BPM, lookahead waveform colors
**Library**: `mss` + `opencv-python`

```python
import mss
import cv2
import numpy as np

class CVSenseNode:
    def __init__(self, bpm_roi: tuple, waveform_roi: tuple):
        """
        bpm_roi: (x, y, width, height) of BPM display
        waveform_roi: (x, y, width, height) of waveform area
        """
        self.bpm_roi = bpm_roi
        self.waveform_roi = waveform_roi
        self.digit_templates = self._load_digit_templates()
        self.sct = mss.mss()

    def _load_digit_templates(self):
        # Pre-rendered digit images matching Rekordbox font
        return {str(i): cv2.imread(f'templates/digit_{i}.png', 0)
                for i in range(10)}

    def _detect_bpm(self, img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)

        digits = []
        for digit, template in self.digit_templates.items():
            result = cv2.matchTemplate(thresh, template, cv2.TM_CCOEFF_NORMED)
            locations = np.where(result >= 0.8)
            for x in locations[1]:
                digits.append((x, digit))

        digits.sort(key=lambda x: x[0])
        bpm_str = ''.join([d[1] for d in digits])
        return float(bpm_str) if bpm_str else None

    def _analyze_waveform_lookahead(self, img, lookahead_pixels=50):
        # Analyze pixels to the right of playhead (center)
        h, w = img.shape[:2]
        center_x = w // 2
        lookahead = img[:, center_x:center_x + lookahead_pixels]

        # Rekordbox 3-band colors: Blue=bass, Amber=mid, White=high
        hsv = cv2.cvtColor(lookahead, cv2.COLOR_BGR2HSV)

        # Blue detection (bass)
        blue_mask = cv2.inRange(hsv, (100, 50, 50), (130, 255, 255))
        bass_intensity = np.sum(blue_mask) / (255 * blue_mask.size)

        # Orange/amber detection (mids)
        amber_mask = cv2.inRange(hsv, (10, 100, 100), (25, 255, 255))
        mid_intensity = np.sum(amber_mask) / (255 * amber_mask.size)

        # White detection (highs)
        white_mask = cv2.inRange(hsv, (0, 0, 200), (180, 30, 255))
        high_intensity = np.sum(white_mask) / (255 * white_mask.size)

        return bass_intensity, mid_intensity, high_intensity

    def __call__(self, state: PhotonicState) -> PhotonicState:
        # Capture BPM region
        bpm_img = np.array(self.sct.grab(self.bpm_roi))
        state['cv_bpm'] = self._detect_bpm(bpm_img)

        # Capture waveform and analyze lookahead
        wave_img = np.array(self.sct.grab(self.waveform_roi))
        bass, mid, high = self._analyze_waveform_lookahead(wave_img)
        state['lookahead_bass'] = bass
        state['lookahead_mids'] = mid
        state['lookahead_highs'] = high

        return state
```

#### Node: `scene_select`
**Purpose**: AI-driven scene selection based on fused state
**Input**: Complete PhotonicState
**Output**: Selected scene name, transition parameters

```python
class SceneSelectNode:
    def __init__(self, scene_configs: dict):
        self.scenes = scene_configs

    def __call__(self, state: PhotonicState) -> PhotonicState:
        structure = state['current_structure']

        # Primary: structure-based selection
        if structure == MusicStructure.DROP:
            state['pending_scene'] = 'drop_intense'
        elif structure == MusicStructure.BUILDUP:
            state['pending_scene'] = 'buildup_tension'
        elif structure == MusicStructure.BREAKDOWN:
            state['pending_scene'] = 'breakdown_ambient'
        else:
            state['pending_scene'] = 'verse_rhythmic'

        # Override: DJ intent (pad triggers = manual override)
        if state['pad_triggers']:
            pad = state['pad_triggers'][-1]
            if pad in self.scenes.get('pad_overrides', {}):
                state['pending_scene'] = self.scenes['pad_overrides'][pad]
                state['pad_triggers'].clear()

        # Lookahead adjustment: pre-load drop scene if bass incoming
        if state['lookahead_bass'] > 0.7 and state['current_structure'] != MusicStructure.DROP:
            state['drop_probability'] = max(state['drop_probability'], 0.8)

        return state
```

#### Node: `dmx_output`
**Purpose**: Thread-safe DMX transmission
**Input**: Fixture commands
**Output**: Updated DMX universe transmitted to fixtures
**Library**: `pyftdi` for Enttec Open DMX USB

```python
import threading
import time
from pyftdi.serialext import serial_for_url

class DMXOutputNode:
    def __init__(self, ftdi_url='ftdi://ftdi:232:FT232R/1'):
        self.universe = bytearray(513)  # Start code + 512 channels
        self.running = True
        self.lock = threading.Lock()

        # Open FTDI serial connection
        self.serial = serial_for_url(
            ftdi_url,
            baudrate=250000,
            bytesize=8,
            stopbits=2
        )

        # Start transmission thread
        self.thread = threading.Thread(target=self._transmit_loop, daemon=True)
        self.thread.start()

    def _transmit_loop(self):
        """Continuous DMX frame transmission at ~40Hz"""
        while self.running:
            with self.lock:
                data = bytes(self.universe)

            # Send break (hold line low for ~100µs)
            self.serial.send_break(duration=0.0001)

            # Mark After Break + data
            time.sleep(0.000012)  # 12µs MAB
            self.serial.write(data)

            # Inter-frame delay (~25ms for 40Hz refresh)
            time.sleep(0.023)

    def __call__(self, state: PhotonicState) -> PhotonicState:
        with self.lock:
            for cmd in state['fixture_commands']:
                for channel, value in cmd['channel_values'].items():
                    self.universe[channel] = max(0, min(255, value))

        state['dmx_universe'] = bytes(self.universe)
        state['fixture_commands'] = []  # Clear processed commands
        return state
```

#### Node: `safety_interlock`
**Purpose**: Enforce safety limits on all DMX output
**Input**: DMX universe buffer
**Output**: Safety-filtered DMX universe
**Always runs last before transmission**

```python
class SafetyInterlockNode:
    # Laser Y-axis (tilt) limits to prevent crowd scanning
    LASER_TILT_CHANNEL = 5
    LASER_TILT_MAX = 100  # Clamp to prevent aiming below horizon

    # Maximum strobe rate (Hz) to prevent seizure risk
    MAX_STROBE_RATE = 10

    def __init__(self, fixture_config: dict):
        self.fixture_config = fixture_config
        self.last_heartbeat = time.time()
        self.strobe_timestamps = deque(maxlen=100)

    def __call__(self, state: PhotonicState) -> PhotonicState:
        universe = bytearray(state['dmx_universe'])

        # 1. Check system heartbeat
        if time.time() - self.last_heartbeat > 1.0:
            # System unresponsive - blackout
            state['safety_ok'] = False
            state['error_state'] = 'heartbeat_timeout'
            return self._emergency_blackout(state)

        # 2. Laser tilt limits
        for fixture in self.fixture_config.get('lasers', []):
            tilt_ch = fixture['start_address'] + self.LASER_TILT_CHANNEL - 1
            if universe[tilt_ch] > self.LASER_TILT_MAX:
                universe[tilt_ch] = self.LASER_TILT_MAX

        # 3. Strobe rate limiting
        # (Implementation omitted for brevity)

        state['dmx_universe'] = bytes(universe)
        state['safety_ok'] = True
        self.last_heartbeat = time.time()

        return state

    def _emergency_blackout(self, state: PhotonicState) -> PhotonicState:
        state['dmx_universe'] = bytes(513)
        return state
```

### 3.4 LangGraph Graph Construction

```python
from langgraph.graph import StateGraph, END

def build_photonic_graph():
    # Initialize nodes
    audio_sense = AudioSenseNode()
    feature_extract = FeatureExtractNode()
    beat_track = BeatTrackNode()
    structure_detect = StructureDetectNode()
    midi_sense = MidiSenseNode()
    cv_sense = CVSenseNode(bpm_roi=(100, 50, 200, 50), waveform_roi=(100, 100, 800, 100))
    scene_select = SceneSelectNode(scene_configs)
    laser_control = LaserControlNode()
    moving_head_control = MovingHeadControlNode()
    panel_control = PanelControlNode()
    dmx_output = DMXOutputNode()
    safety_interlock = SafetyInterlockNode(fixture_config)

    # Build graph
    graph = StateGraph(PhotonicState)

    # Add nodes
    graph.add_node("audio_sense", audio_sense)
    graph.add_node("feature_extract", feature_extract)
    graph.add_node("beat_track", beat_track)
    graph.add_node("structure_detect", structure_detect)
    graph.add_node("midi_sense", midi_sense)
    graph.add_node("cv_sense", cv_sense)
    graph.add_node("fusion", fusion_node)
    graph.add_node("scene_select", scene_select)
    graph.add_node("laser_control", laser_control)
    graph.add_node("moving_head_control", moving_head_control)
    graph.add_node("panel_control", panel_control)
    graph.add_node("dmx_output", dmx_output)
    graph.add_node("safety_interlock", safety_interlock)

    # Define edges (parallel where possible)
    graph.set_entry_point("audio_sense")

    # Parallel audio analysis paths
    graph.add_edge("audio_sense", "feature_extract")
    graph.add_edge("audio_sense", "beat_track")
    graph.add_edge("audio_sense", "midi_sense")
    graph.add_edge("audio_sense", "cv_sense")

    # Converge to fusion
    graph.add_edge("feature_extract", "structure_detect")
    graph.add_edge("structure_detect", "fusion")
    graph.add_edge("beat_track", "fusion")
    graph.add_edge("midi_sense", "fusion")
    graph.add_edge("cv_sense", "fusion")

    # Scene selection
    graph.add_edge("fusion", "scene_select")

    # Parallel fixture control
    graph.add_edge("scene_select", "laser_control")
    graph.add_edge("scene_select", "moving_head_control")
    graph.add_edge("scene_select", "panel_control")

    # Converge to DMX output
    graph.add_edge("laser_control", "dmx_output")
    graph.add_edge("moving_head_control", "dmx_output")
    graph.add_edge("panel_control", "dmx_output")

    # Safety check before output
    graph.add_edge("dmx_output", "safety_interlock")

    # Loop back (continuous operation)
    graph.add_edge("safety_interlock", "audio_sense")

    return graph.compile()
```

---

## 4. Scene Configuration Schema

### 4.1 Scene JSON Structure

```json
{
  "name": "drop_intense",
  "description": "High-energy drop with full strobe and laser chaos",
  "priority": 100,
  "triggers": {
    "structure": ["drop"],
    "energy_threshold": 0.8,
    "bass_threshold": 0.7
  },
  "fixtures": {
    "lasers": {
      "mode": "dmx_control",
      "pattern": "random_switch",
      "pattern_rate": "beat_sync",
      "zoom": {
        "mode": "oscillate",
        "min": 0,
        "max": 255,
        "rate": "beat_sync"
      },
      "x_roll": {"mode": "random", "range": [0, 255]},
      "y_roll": {"mode": "static", "value": 64, "max_clamp": 100},
      "movement_speed": {"mode": "linked", "source": "spectral_flux", "scale": 2.0},
      "color": {"mode": "cycle", "rate": "bar_sync", "palette": ["green", "red", "blue"]}
    },
    "moving_heads": {
      "pan": {
        "mode": "lissajous",
        "frequency_x": 1.0,
        "frequency_y": 0.5,
        "phase": 0,
        "scale": "bpm_linked"
      },
      "tilt": {
        "mode": "beat_pulse",
        "min": 64,
        "max": 192,
        "attack": 0.1,
        "decay": 0.3
      },
      "color": {"mode": "static", "value": "white"},
      "gobo": {"mode": "static", "value": "open"},
      "dimmer": {"mode": "linked", "source": "rms_energy", "min": 128, "max": 255}
    },
    "panels": {
      "mode": "strobe",
      "rate": {"mode": "linked", "source": "beat_phase", "multiplier": 4},
      "color": {"mode": "flash", "value": "white", "fallback": "black"}
    }
  },
  "transitions": {
    "fade_in_time": 0.0,
    "fade_out_time": 0.5
  }
}
```

### 4.2 Fixture Profile Schema

```yaml
# config/fixtures/laser_generic_7ch.yaml
name: "Generic 7-Channel Laser"
manufacturer: "Generic"
channels: 7
channel_map:
  1:
    name: "mode"
    type: "mode_select"
    values:
      blackout: [0, 63]
      auto: [64, 127]
      sound_active: [128, 191]
      dmx_control: [192, 255]
  2:
    name: "pattern"
    type: "pattern_select"
    range: [0, 255]
    patterns: 64
  3:
    name: "zoom"
    type: "continuous"
    range: [0, 255]
    fixed: [0, 127]
    animate: [128, 255]
  4:
    name: "x_roll"
    type: "continuous"
    range: [0, 255]
  5:
    name: "y_roll"
    type: "continuous"
    range: [0, 255]
    safety_clamp: 100  # Prevent crowd scanning
  6:
    name: "movement_speed"
    type: "speed"
    range: [0, 255]
    slow: [0, 127]
    fast: [128, 255]
  7:
    name: "color"
    type: "color_select"
    range: [0, 255]
```

---

## 5. Safety Architecture

### 5.1 Multi-Layer Safety System

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           SAFETY ARCHITECTURE                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Layer 1: HARDWARE INTERLOCKS (Physical)                                    │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ • E-Stop button (cuts power to all fixtures)                           │ │
│  │ • Key switch (master enable)                                           │ │
│  │ • Laser mechanical shutter (fail-safe closed)                          │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Layer 2: DMX PROTOCOL SAFETY (Transmission)                                │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ • Watchdog: If no valid DMX for 1s → fixtures auto-blackout            │ │
│  │ • Continuous transmission: 40Hz minimum refresh                        │ │
│  │ • Checksum verification (if supported by fixtures)                     │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Layer 3: SOFTWARE INTERLOCKS (Python)                                      │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ • Laser Y-axis clamping (prevent crowd scanning)                       │ │
│  │ • Strobe rate limiting (max 10Hz for seizure safety)                   │ │
│  │ • Beat confidence threshold (low confidence → reduce intensity)        │ │
│  │ • Thread health monitoring (analysis hang → blackout)                  │ │
│  │ • UV exposure time limits                                               │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Layer 4: OPERATIONAL SAFETY (Human)                                        │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ • Laser safety officer required for Class 3B+ lasers                   │ │
│  │ • Pre-show fixture position verification                               │ │
│  │ • Exclusion zone enforcement                                            │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Safety Configuration

```yaml
# config/safety.yaml
safety:
  laser:
    y_axis_max: 100              # Max tilt value (0-255), prevents aiming at crowd
    min_scan_speed: 30           # Minimum galvo speed (prevents static beam burns)
    max_intensity_no_movement: 50  # Reduce power if scanners stationary
    enable_delay_ms: 500         # Delay before laser enables after scene change

  strobe:
    max_rate_hz: 10              # Maximum strobe frequency
    max_duration_s: 5            # Maximum continuous strobe duration
    cooldown_s: 2                # Minimum gap between strobe bursts

  moving_head:
    max_pan_speed: 200           # Limit pan speed for mechanical safety
    max_tilt_speed: 200          # Limit tilt speed
    home_on_error: true          # Return to home position on error

  system:
    heartbeat_timeout_s: 1.0     # Max time without heartbeat before blackout
    analysis_timeout_s: 2.0      # Max time for audio analysis before fallback
    min_beat_confidence: 0.3     # Below this, reduce reactive intensity
    graceful_degradation: true   # Continue with reduced features on sensor failure
```

---

## 6. Implementation Phases

### Phase 1: Core Infrastructure (Week 1-2)
- [ ] Project scaffolding and dependency setup
- [ ] DMX interface driver (pyftdi for Enttec Open DMX USB)
- [ ] Basic fixture profiles (laser, moving head, panel)
- [ ] Safety interlock system
- [ ] Manual DMX control CLI for testing

### Phase 2: Audio Analysis Pipeline (Week 3-4)
- [ ] Real-time audio capture (sounddevice)
- [ ] Feature extraction (librosa: RMS, spectral centroid, band energies)
- [ ] Beat tracking (BeatNet or madmom online mode)
- [ ] Structure detection (drop/buildup/breakdown heuristics)

### Phase 3: Multi-Modal Fusion (Week 5-6)
- [ ] MIDI input processing (mido + XDJ-AZ mappings)
- [ ] Computer vision pipeline (mss + OpenCV for BPM/waveform)
- [ ] State fusion node
- [ ] Scene selection logic

### Phase 4: LangGraph Integration (Week 7-8)
- [ ] State definition and graph construction
- [ ] Node implementations
- [ ] Edge routing and conditional logic
- [ ] Continuous loop operation

### Phase 5: Scene Engine (Week 9-10)
- [ ] JSON scene loader
- [ ] Scene transition system
- [ ] Fixture-specific effect generators
- [ ] BPM-synced movement patterns

### Phase 6: Testing & Refinement (Week 11-12)
- [ ] Unit tests for all components
- [ ] Integration tests with mock fixtures
- [ ] Real hardware testing
- [ ] Performance optimization
- [ ] Documentation

---

## 7. Dependencies

```toml
# pyproject.toml
[project]
name = "photonic-synesthesia"
version = "0.1.0"
description = "AI-driven laser show controller for XDJ-AZ"
requires-python = ">=3.10"

dependencies = [
    # LangGraph Orchestration
    "langgraph>=0.2.0",
    "langchain-core>=0.3.0",

    # Audio Analysis
    "numpy>=1.24.0",
    "scipy>=1.11.0",
    "librosa>=0.10.0",
    "sounddevice>=0.4.6",
    "BeatNet>=1.1.0",

    # MIDI
    "mido>=1.3.0",
    "python-rtmidi>=1.5.0",

    # Computer Vision
    "opencv-python>=4.8.0",
    "mss>=9.0.0",

    # DMX Control
    "pyftdi>=0.55.0",

    # Configuration
    "pyyaml>=6.0",
    "pydantic>=2.0",

    # Optional: ML/Clustering
    "scikit-learn>=1.3.0",
    "torch>=2.0.0",  # For BeatNet
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4.0",
    "pytest-asyncio>=0.21.0",
    "black>=23.0.0",
    "ruff>=0.1.0",
    "mypy>=1.5.0",
]
web = [
    "fastapi>=0.103.0",
    "uvicorn>=0.23.0",
    "websockets>=11.0",
]
```

---

## 8. Key Technical Considerations

### 8.1 Threading Strategy

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          THREAD ARCHITECTURE                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Thread 1: DMX TRANSMISSION (High Priority)                                 │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ • Runs at 40Hz continuous                                              │ │
│  │ • Reads from shared DMX buffer (lock-protected)                        │ │
│  │ • NEVER blocks on audio analysis                                       │ │
│  │ • Implements break/MAB timing via pyftdi                               │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Thread 2: AUDIO CAPTURE (Real-time Priority)                               │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ • sounddevice callback thread (managed by PortAudio)                   │ │
│  │ • Fills ring buffer with audio samples                                 │ │
│  │ • Minimal processing in callback                                       │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Thread 3: MIDI INPUT (Event-driven)                                        │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ • mido callback thread                                                 │ │
│  │ • Pushes events to thread-safe queue                                   │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Thread 4: ANALYSIS + LANGGRAPH (Main)                                      │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ • Runs LangGraph state machine loop                                    │ │
│  │ • Performs heavy FFT/ML computations                                   │ │
│  │ • Writes to shared DMX buffer                                          │ │
│  │ • Target: 50Hz update rate                                             │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Thread 5: CV CAPTURE (Low Priority)                                        │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ • Screen capture at 5-10Hz                                             │ │
│  │ • OCR processing                                                       │ │
│  │ • Updates shared state                                                 │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 8.2 Latency Budget

| Stage | Target Latency | Notes |
|-------|----------------|-------|
| Audio capture | <10ms | Depends on buffer size |
| Feature extraction | <20ms | librosa STFT on 2048 samples |
| Beat tracking | <50ms | BeatNet inference |
| MIDI processing | <1ms | Event-driven |
| Scene selection | <5ms | Lookup + interpolation |
| DMX transmission | 25ms | One frame at 40Hz |
| **Total audio-to-light** | **<100ms** | Imperceptible at dance tempo |

### 8.3 Fallback Modes

```python
class FallbackManager:
    """Graceful degradation when sensors fail"""

    def get_fallback_state(self, failed_sensors: set) -> PhotonicState:
        state = PhotonicState()

        if 'audio' in failed_sensors:
            # Fall back to MIDI-only mode
            state['current_bpm'] = 128.0  # Default EDM tempo
            state['beat_phase'] = (time.time() % 0.469) / 0.469  # 128 BPM phase

        if 'midi' in failed_sensors:
            # Assume neutral mixer state
            state['crossfader_position'] = 0.0
            state['channel_faders'] = [1.0, 1.0, 1.0, 1.0]

        if 'cv' in failed_sensors:
            # Use audio-derived BPM only
            state['cv_bpm'] = None
            state['lookahead_bass'] = state.get('low_energy', 0.5)

        return state
```

---

## 9. Research Sources

### Audio Analysis
- [librosa documentation](https://librosa.org/doc/main/index.html)
- [BeatNet GitHub](https://github.com/mjhydri/BeatNet) - CRNN + Particle Filtering
- [madmom documentation](https://madmom.readthedocs.io/)
- [python-sounddevice](https://python-sounddevice.readthedocs.io/)

### DMX Control
- [Enttec Open DMX USB on Stack Overflow](https://stackoverflow.com/questions/15732608/how-to-control-enttec-open-dmx-usb-via-python)
- [PyDMXControl](https://pypi.org/project/PyDMXControl/)
- [pyftdi documentation](https://eblot.github.io/pyftdi/)
- [pyopendmx](https://github.com/maximecb/pyopendmx) - Music-reactive DMX

### LangGraph
- [LangGraph GitHub](https://github.com/langchain-ai/langgraph)
- [LangGraph Python Tutorial](https://realpython.com/langgraph-python/)
- [deepagents](https://github.com/langchain-ai/deepagents) - Subagent patterns

### Reference Projects
- [Oculizer](https://github.com/LandryBulls/Oculizer) - ML-driven DMX automation
- [sound-to-light-osc](https://github.com/scheb/sound-to-light-osc) - Beat detection

### XDJ-AZ
- [AlphaTheta XDJ-AZ Product Page](https://alphatheta.com/en/information/meet-the-xdj-az-4-channel-professional-all-in-one-dj-system/)
- [XDJ-AZ MIDI Mapping](https://www.pioneerdj.com/en/support/software-information/xdj-az/)

---

## 10. Next Steps

1. **Validate hardware compatibility**: Test Enttec Open DMX USB with pyftdi
2. **Prototype audio pipeline**: Standalone script testing librosa + BeatNet
3. **Create fixture test rig**: Basic DMX control of one laser
4. **Build LangGraph skeleton**: Minimal graph with 3 nodes
5. **Iterate**: Add nodes incrementally, testing each layer

---

*Document Version: 1.0*
*Last Updated: December 2024*
