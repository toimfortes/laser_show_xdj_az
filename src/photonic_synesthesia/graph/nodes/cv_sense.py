"""
CV Sense Node: Computer vision for screen reading.

Captures BPM display and waveform from Rekordbox screen using
template matching for digit OCR and color analysis for waveform lookahead.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import cast

import numpy as np
import structlog

from photonic_synesthesia.core.config import CVConfig
from photonic_synesthesia.core.state import CVState, PhotonicState

logger = structlog.get_logger()

try:
    import cv2
    import mss

    CV_AVAILABLE = True
except ImportError:
    CV_AVAILABLE = False
    cv2 = None
    mss = None


class CVSenseNode:
    """
    Reads BPM and waveform information from Rekordbox screen.

    Uses screen capture with mss and template matching with OpenCV
    for fast, reliable digit recognition.
    """

    def __init__(self, config: CVConfig):
        self.config = config
        self.enabled = config.enabled and CV_AVAILABLE

        # Screen capture
        self._sct = None
        if CV_AVAILABLE:
            self._sct = mss.mss()

        # Digit templates for OCR
        self._digit_templates: dict[str, np.ndarray] = {}

        # Capture regions (to be configured)
        self._bpm_roi = config.bpm_roi  # {"x": 100, "y": 50, "width": 200, "height": 50}
        self._waveform_roi = config.waveform_roi

        # Rate limiting
        self._last_capture_time: float = 0.0
        self._capture_interval: float = 1.0 / config.capture_rate_hz

        # Results cache
        self._last_bpm: float | None = None
        self._last_lookahead: tuple[float, float, float] = (0.5, 0.5, 0.5)

    def _load_digit_templates(self, template_dir: Path) -> None:
        """Load pre-rendered digit templates for template matching."""
        if not CV_AVAILABLE:
            return

        for digit in "0123456789.":
            template_path = template_dir / f"digit_{digit}.png"
            if template_path.exists():
                template = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
                self._digit_templates[digit] = template

    def __call__(self, state: PhotonicState) -> PhotonicState:
        """Capture screen and extract BPM/waveform data."""
        start_time = time.time()
        current_time = state["timestamp"]

        if not self.enabled:
            state["sensor_status"]["cv"] = False
            return state

        # Rate limiting
        if current_time - self._last_capture_time < self._capture_interval:
            # Use cached values
            state["cv_state"] = CVState(
                detected_bpm=self._last_bpm,
                lookahead_bass=self._last_lookahead[0],
                lookahead_mids=self._last_lookahead[1],
                lookahead_highs=self._last_lookahead[2],
                waveform_phase=0.0,
                capture_timestamp=self._last_capture_time,
            )
            return state

        self._last_capture_time = current_time

        try:
            # Capture BPM region
            if self._bpm_roi:
                bpm = self._detect_bpm()
                if bpm is not None:
                    self._last_bpm = bpm

            # Capture waveform region
            if self._waveform_roi:
                self._last_lookahead = self._analyze_waveform()

            state["sensor_status"]["cv"] = True

        except Exception as e:
            logger.error("CV capture failed", error=str(e))
            state["sensor_status"]["cv"] = False

        # Update state
        state["cv_state"] = CVState(
            detected_bpm=self._last_bpm,
            lookahead_bass=self._last_lookahead[0],
            lookahead_mids=self._last_lookahead[1],
            lookahead_highs=self._last_lookahead[2],
            waveform_phase=0.0,
            capture_timestamp=current_time,
        )

        # Record processing time
        state["processing_times"]["cv_sense"] = time.time() - start_time

        return state

    def _capture_region(self, roi: dict[str, int]) -> np.ndarray | None:
        """Capture a screen region."""
        if not self._sct:
            return None

        monitor = {
            "left": roi["x"],
            "top": roi["y"],
            "width": roi["width"],
            "height": roi["height"],
        }

        screenshot = self._sct.grab(monitor)
        img = np.array(screenshot)

        # Convert BGRA to BGR
        converted = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        return cast(np.ndarray, np.asarray(converted))

    def _detect_bpm(self) -> float | None:
        """Detect BPM from screen using template matching."""
        if not self._bpm_roi:
            return None

        img = self._capture_region(self._bpm_roi)
        if img is None:
            return None

        # Convert to grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Apply threshold to isolate bright text
        _, thresh = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)

        # If we have digit templates, use template matching
        if self._digit_templates:
            return self._match_digits(thresh)

        # Fallback: Use Tesseract OCR if available
        try:
            import pytesseract

            text = pytesseract.image_to_string(thresh, config="--psm 7 digits").strip()
            # Parse BPM (format: "128.00" or "128")
            text = "".join(c for c in text if c.isdigit() or c == ".")
            if text:
                return float(text)
        except ImportError:
            pass

        return None

    def _match_digits(self, img: np.ndarray) -> float | None:
        """Match digit templates to extract BPM."""
        matches = []

        for digit, template in self._digit_templates.items():
            result = cv2.matchTemplate(img, template, cv2.TM_CCOEFF_NORMED)
            locations = np.where(result >= 0.7)

            for x in locations[1]:
                matches.append((x, digit))

        if not matches:
            return None

        # Sort by x position
        matches.sort(key=lambda m: m[0])

        # Build number string
        bpm_str = "".join(m[1] for m in matches)

        try:
            return float(bpm_str)
        except ValueError:
            return None

    def _analyze_waveform(self) -> tuple[float, float, float]:
        """
        Analyze waveform colors ahead of playhead.

        Rekordbox 3-band waveforms use:
        - Blue: Bass/low frequencies
        - Orange/Amber: Mids
        - White: Highs
        """
        if not self._waveform_roi:
            return (0.5, 0.5, 0.5)

        img = self._capture_region(self._waveform_roi)
        if img is None:
            return (0.5, 0.5, 0.5)

        h, w = img.shape[:2]
        center_x = w // 2

        # Analyze pixels to the right of center (lookahead)
        lookahead_width = self.config.lookahead_pixels
        lookahead = img[:, center_x : center_x + lookahead_width]

        # Convert to HSV for color detection
        hsv = cv2.cvtColor(lookahead, cv2.COLOR_BGR2HSV)

        # Blue detection (bass) - H: 100-130
        blue_mask = cv2.inRange(hsv, (100, 50, 50), (130, 255, 255))
        bass_intensity = np.sum(blue_mask) / (255 * blue_mask.size)

        # Orange/amber detection (mids) - H: 10-25
        amber_mask = cv2.inRange(hsv, (10, 100, 100), (25, 255, 255))
        mid_intensity = np.sum(amber_mask) / (255 * amber_mask.size)

        # White detection (highs) - Low saturation, high value
        white_mask = cv2.inRange(hsv, (0, 0, 200), (180, 30, 255))
        high_intensity = np.sum(white_mask) / (255 * white_mask.size)

        return (
            float(np.clip(bass_intensity * 5, 0, 1)),  # Scale up
            float(np.clip(mid_intensity * 5, 0, 1)),
            float(np.clip(high_intensity * 5, 0, 1)),
        )

    def configure_regions(
        self,
        bpm_roi: dict[str, int] | None = None,
        waveform_roi: dict[str, int] | None = None,
    ) -> None:
        """Configure capture regions."""
        if bpm_roi:
            self._bpm_roi = bpm_roi
        if waveform_roi:
            self._waveform_roi = waveform_roi
