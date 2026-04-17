"""Rekordbox export helpers for track matching and structure import."""

from __future__ import annotations

import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

_STRUCTURE_ALIASES = {
    "intro": "intro",
    "build": "build",
    "build2": "build",
    "drop": "drop",
    "breakdown": "breakdown",
    "outro": "outro",
    "bridge": "bridge",
    "verse": "verse",
    "chorus": "chorus",
    "vocal": "vocal",
}


@dataclass(slots=True)
class RekordboxStructureMarker:
    """Normalized phrase/structure marker from a Rekordbox export."""

    name: str
    kind: str
    start_seconds: float
    energy_hint: int | None = None


@dataclass(slots=True)
class RekordboxTrack:
    """Track metadata plus imported structure markers."""

    track_id: str
    title: str
    artist: str
    location: str
    total_time: float
    average_bpm: float | None = None
    markers: list[RekordboxStructureMarker] = field(default_factory=list)


def _normalize_text(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _location_basename(location: str) -> str:
    parsed = urllib.parse.urlparse(location)
    if parsed.scheme == "file":
        path = urllib.parse.unquote(parsed.path or "")
        if path.startswith("/") and len(path) > 2 and path[2] == ":":
            path = path[1:]
        path = path.replace("\\", "/")
        return Path(path).name
    return Path(location).name


def _normalized_track_candidates(track_element: ET.Element) -> set[str]:
    location = str(track_element.attrib.get("Location", ""))
    basename = _location_basename(location)
    title = str(track_element.attrib.get("Name", "")).strip()
    artist = str(track_element.attrib.get("Artist", "")).strip()
    return {
        _normalize_text(basename),
        _normalize_text(Path(basename).stem),
        _normalize_text(title),
        _normalize_text(f"{artist}{title}"),
        _normalize_text(f"{title}{artist}"),
    }


def _classify_marker(name: str) -> tuple[str, int | None]:
    compact = _normalize_text(name)
    energy_match = re.search(r"e[: ]?(\d+)", name.lower())
    energy_hint = int(energy_match.group(1)) if energy_match else None
    for alias, kind in _STRUCTURE_ALIASES.items():
        if compact.startswith(alias):
            return kind, energy_hint
    return "marker", energy_hint


def _parse_markers(track_element: ET.Element) -> list[RekordboxStructureMarker]:
    dedupe: set[tuple[str, int]] = set()
    markers: list[RekordboxStructureMarker] = []
    for mark in track_element.findall("POSITION_MARK"):
        name = str(mark.attrib.get("Name", "")).strip()
        if not name:
            continue
        start_raw = mark.attrib.get("Start")
        if start_raw is None:
            continue
        try:
            start_seconds = float(start_raw)
        except ValueError:
            continue
        kind, energy_hint = _classify_marker(name)
        if kind == "marker":
            continue
        key = (kind, int(round(start_seconds * 1000)))
        if key in dedupe:
            continue
        dedupe.add(key)
        markers.append(
            RekordboxStructureMarker(
                name=name,
                kind=kind,
                start_seconds=start_seconds,
                energy_hint=energy_hint,
            )
        )
    markers.sort(key=lambda item: item.start_seconds)
    return markers


def load_rekordbox_track(
    xml_path: str | Path,
    audio_file: str | Path,
    *,
    audio_duration_seconds: float | None = None,
    expected_bpm: float | None = None,
) -> RekordboxTrack | None:
    """Load the best matching Rekordbox export track for an audio file."""
    xml_file = Path(xml_path)
    audio_path = Path(audio_file)
    if not xml_file.is_file():
        return None

    tree = ET.parse(xml_file)
    collection = tree.getroot().find("COLLECTION")
    if collection is None:
        return None

    normalized_file = _normalize_text(audio_path.name)
    normalized_stem = _normalize_text(audio_path.stem)

    ranked_matches: list[tuple[int, RekordboxTrack]] = []
    for track_element in collection.findall("TRACK"):
        location = str(track_element.attrib.get("Location", ""))
        title = str(track_element.attrib.get("Name", "")).strip()
        artist = str(track_element.attrib.get("Artist", "")).strip()
        candidates = _normalized_track_candidates(track_element)

        score = 0
        if normalized_file and normalized_file in candidates:
            score = max(score, 400)
        if normalized_stem and normalized_stem in candidates:
            score = max(score, 320)
        if normalized_stem and any(normalized_stem and normalized_stem in item for item in candidates):
            score = max(score, 180)
        if not score:
            continue

        try:
            total_time = float(track_element.attrib.get("TotalTime", "0"))
        except ValueError:
            total_time = 0.0
        try:
            average_bpm = float(track_element.attrib.get("AverageBpm", "0") or 0)
        except ValueError:
            average_bpm = None

        if audio_duration_seconds is not None and total_time > 0:
            duration_delta = abs(total_time - audio_duration_seconds)
            if duration_delta <= 2.0:
                score += 60
            elif duration_delta <= 6.0:
                score += 30
            elif duration_delta > 15.0:
                continue
        if expected_bpm is not None and average_bpm:
            bpm_delta = abs(average_bpm - expected_bpm)
            if bpm_delta <= 0.75:
                score += 20
            elif bpm_delta <= 2.0:
                score += 10
            elif bpm_delta > 8.0:
                score -= 40

        ranked_matches.append(
            (
                score,
                RekordboxTrack(
                    track_id=str(track_element.attrib.get("TrackID", "")),
                    title=title or audio_path.stem,
                    artist=artist,
                    location=location,
                    total_time=total_time,
                    average_bpm=average_bpm or None,
                    markers=_parse_markers(track_element),
                ),
            )
        )

    if not ranked_matches:
        return None

    ranked_matches.sort(key=lambda item: item[0], reverse=True)
    if len(ranked_matches) > 1 and ranked_matches[1][0] == ranked_matches[0][0]:
        return None
    return ranked_matches[0][1]


def load_rekordbox_track_by_metadata(
    xml_path: str | Path,
    *,
    title: str,
    artist: str = "",
    duration_seconds: float | None = None,
    expected_bpm: float | None = None,
) -> RekordboxTrack | None:
    """Load the best matching Rekordbox export track for live metadata."""
    xml_file = Path(xml_path)
    if not xml_file.is_file():
        return None

    normalized_title = _normalize_text(title)
    normalized_artist = _normalize_text(artist)
    if not normalized_title:
        return None

    tree = ET.parse(xml_file)
    collection = tree.getroot().find("COLLECTION")
    if collection is None:
        return None

    ranked_matches: list[tuple[int, RekordboxTrack]] = []
    for track_element in collection.findall("TRACK"):
        track_title = str(track_element.attrib.get("Name", "")).strip()
        track_artist = str(track_element.attrib.get("Artist", "")).strip()
        normalized_track_title = _normalize_text(track_title)
        normalized_track_artist = _normalize_text(track_artist)

        if not normalized_track_title:
            continue

        score = 0
        if normalized_track_title == normalized_title:
            score = max(score, 360)
        elif normalized_title in normalized_track_title or normalized_track_title in normalized_title:
            score = max(score, 180)
        else:
            continue

        if normalized_artist and normalized_track_artist:
            if normalized_track_artist == normalized_artist:
                score += 180
            elif normalized_artist in normalized_track_artist or normalized_track_artist in normalized_artist:
                score += 90
            else:
                score -= 120
        elif normalized_artist:
            score -= 30

        try:
            total_time = float(track_element.attrib.get("TotalTime", "0"))
        except ValueError:
            total_time = 0.0
        try:
            average_bpm = float(track_element.attrib.get("AverageBpm", "0") or 0)
        except ValueError:
            average_bpm = None

        if duration_seconds is not None and total_time > 0:
            duration_delta = abs(total_time - duration_seconds)
            if duration_delta <= 2.0:
                score += 60
            elif duration_delta <= 6.0:
                score += 30
            elif duration_delta > 15.0:
                score -= 90
        if expected_bpm is not None and average_bpm:
            bpm_delta = abs(average_bpm - expected_bpm)
            if bpm_delta <= 0.75:
                score += 20
            elif bpm_delta <= 2.0:
                score += 10
            elif bpm_delta > 8.0:
                score -= 40

        if score <= 0:
            continue

        ranked_matches.append(
            (
                score,
                RekordboxTrack(
                    track_id=str(track_element.attrib.get("TrackID", "")),
                    title=track_title or title,
                    artist=track_artist or artist,
                    location=str(track_element.attrib.get("Location", "")),
                    total_time=total_time,
                    average_bpm=average_bpm or None,
                    markers=_parse_markers(track_element),
                ),
            )
        )

    if not ranked_matches:
        return None

    ranked_matches.sort(key=lambda item: item[0], reverse=True)
    if len(ranked_matches) > 1 and ranked_matches[1][0] == ranked_matches[0][0]:
        return None
    return ranked_matches[0][1]


def find_matching_track(xml_path: str | Path, audio_file: str | Path) -> RekordboxTrack | None:
    """Backwards-compatible alias for track matching."""
    return load_rekordbox_track(xml_path, audio_file)
