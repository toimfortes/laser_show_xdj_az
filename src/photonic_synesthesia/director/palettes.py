"""Named color palettes used by the director to drive fixture hue.

The director produces a ``color_theme`` string per frame based on music
structure and audio features. Fixtures (moving heads, lasers) and the
ILDA renderer resolve that string to a :class:`Palette` here and render
its three RGB tuples according to their local ``color_mode`` style
(``static`` / ``morph`` / ``dual_cycle`` / ``white_hits``).

This decouples **what color** (director's decision) from **how to
render it** (fixture / ILDA style).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

RGB = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class Palette:
    """A minimal palette: primary hue, secondary hue, accent flash.

    Values are 0-255 RGB.
    """

    primary: RGB
    secondary: RGB
    accent: RGB
    name: str


# Core palette set. Keep small so the director's deterministic picker
# produces legible, recognisable looks rather than muddled averages.
_PALETTES: dict[str, Palette] = {
    "neutral": Palette(
        primary=(180, 180, 200),
        secondary=(90, 100, 140),
        accent=(255, 255, 255),
        name="neutral",
    ),
    "warm": Palette(
        primary=(255, 140, 40),
        secondary=(200, 60, 120),
        accent=(255, 230, 180),
        name="warm",
    ),
    "cool": Palette(
        primary=(40, 140, 255),
        secondary=(90, 230, 255),
        accent=(240, 240, 255),
        name="cool",
    ),
    "white_hot": Palette(
        primary=(255, 255, 255),
        secondary=(255, 210, 120),
        accent=(255, 255, 255),
        name="white_hot",
    ),
    "cyan_magenta": Palette(
        primary=(40, 220, 255),
        secondary=(240, 40, 200),
        accent=(255, 255, 255),
        name="cyan_magenta",
    ),
    "deep_blue": Palette(
        primary=(20, 60, 200),
        secondary=(120, 40, 220),
        accent=(180, 200, 255),
        name="deep_blue",
    ),
    "amber_cyan": Palette(
        primary=(255, 170, 40),
        secondary=(40, 210, 220),
        accent=(255, 255, 255),
        name="amber_cyan",
    ),
    "emerald_violet": Palette(
        primary=(40, 220, 120),
        secondary=(160, 40, 220),
        accent=(240, 255, 220),
        name="emerald_violet",
    ),
    "breakdown_blue": Palette(
        primary=(40, 100, 220),
        secondary=(80, 200, 255),
        accent=(220, 230, 255),
        name="breakdown_blue",
    ),
}


DEFAULT_PALETTE = _PALETTES["neutral"]


def resolve_palette(color_theme: str | None) -> Palette:
    """Map a ``color_theme`` string to its palette.

    Unknown themes fall back to ``neutral``. The old short strings
    (``"warm"``, ``"cool"``, ``"white-hot"``, ``"neutral"``) are
    accepted so the director and its consumers can evolve independently.
    """
    if not color_theme:
        return DEFAULT_PALETTE
    key = color_theme.replace("-", "_").strip().lower()
    if key == "white_hot":
        return _PALETTES["white_hot"]
    return _PALETTES.get(key, DEFAULT_PALETTE)


def available_theme_names() -> tuple[str, ...]:
    """Return the canonical theme names the director may pick from."""
    return tuple(_PALETTES.keys())


# ---------------------------------------------------------------------------
# Rendering helpers — given a palette and a "style" (color_mode) and a phase,
# produce an RGB. Used by both fixture_control and ilda_output so the two
# renderers agree.
# ---------------------------------------------------------------------------


def _lerp(a: int, b: int, t: float) -> int:
    return int(round(a + (b - a) * max(0.0, min(1.0, t))))


def _blend(lhs: RGB, rhs: RGB, t: float) -> RGB:
    return (_lerp(lhs[0], rhs[0], t), _lerp(lhs[1], rhs[1], t), _lerp(lhs[2], rhs[2], t))


def render_rgb(
    palette: Palette,
    color_mode: str,
    *,
    phase: float = 0.0,
    beat_hit: bool = False,
    color_drive: float = 0.5,
) -> RGB:
    """Compose an RGB value from a palette + a rendering style.

    ``color_mode`` is the fixture/laser-local rendering mode produced by
    :func:`photonic_synesthesia.showplan.laser_program._laser_color_mode_for_strategy`
    or by per-section ``_variants.laser_expression``.

    - ``"static"``: hold the primary hue.
    - ``"white_hits"``: flash the accent on beat, otherwise secondary.
    - ``"dual_cycle"``: sinusoidal primary ⇄ secondary.
    - ``"morph"``: continuous primary → secondary → accent → primary sweep.
    - anything else: graceful fallback to ``static``.

    ``phase`` is an arbitrary 0..2π-style value; callers can pass a
    time-based phase for animated modes.
    ``color_drive`` biases mixes toward the accent for higher-energy
    sections (0..1).
    """
    mode = (color_mode or "").strip().lower()
    drive = max(0.0, min(1.0, float(color_drive)))

    if mode == "white_hits":
        if beat_hit:
            return palette.accent
        return _blend(palette.secondary, palette.accent, drive * 0.35)

    if mode == "dual_cycle":
        t = 0.5 + 0.5 * math.sin(phase)
        base = _blend(palette.primary, palette.secondary, t)
        return _blend(base, palette.accent, drive * 0.25)

    if mode == "morph":
        # Three-stop sweep primary → secondary → accent → primary
        cycle = (phase / (2.0 * math.pi)) % 1.0
        if cycle < 1.0 / 3.0:
            t = cycle * 3.0
            return _blend(palette.primary, palette.secondary, t)
        if cycle < 2.0 / 3.0:
            t = (cycle - 1.0 / 3.0) * 3.0
            return _blend(palette.secondary, palette.accent, t)
        t = (cycle - 2.0 / 3.0) * 3.0
        return _blend(palette.accent, palette.primary, t)

    # static / unknown → primary, slightly biased toward accent by drive
    return _blend(palette.primary, palette.accent, drive * 0.15)
