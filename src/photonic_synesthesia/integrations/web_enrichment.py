"""Web metadata enrichment for offline show catalogs."""

from __future__ import annotations

import html
import json
import re
import urllib.parse
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

_WEB_ENRICHMENT_VERSION = 1
_USER_AGENT = "Mozilla/5.0 (compatible; PhotonicSynesthesia/0.1.0)"
_REQUEST_TIMEOUT_SECONDS = 4.0


def _normalize_text(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", _normalize_text_with_spaces(value))
    return cleaned.strip("-")


def _normalize_text_with_spaces(value: str) -> str:
    value = html.unescape(value).lower()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _request_text(url: str) -> str:
    request = urllib_request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib_request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
        return response.read().decode("utf-8", "ignore")


def _request_json(url: str) -> Any:
    return json.loads(_request_text(url))


def _safe_float(value: Any) -> float | None:
    if isinstance(value, str):
        compact = value.strip()
        if re.fullmatch(r"\d+(?::\d{1,2}){1,2}", compact):
            parts = [int(part) for part in compact.split(":")]
            seconds = 0
            for part in parts:
                seconds = (seconds * 60) + part
            return float(seconds)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_duration_seconds(value: Any) -> float | None:
    numeric = _safe_float(value)
    if numeric is None:
        return None
    if numeric > 10000:
        return round(numeric / 1000.0, 3)
    return numeric


def _score_match(
    *,
    expected_title: str,
    expected_artist: str,
    candidate_title: str,
    candidate_artist: str,
    expected_duration_seconds: float | None = None,
    candidate_duration_seconds: float | None = None,
) -> float:
    title_score = SequenceMatcher(
        None,
        _normalize_text_with_spaces(expected_title),
        _normalize_text_with_spaces(candidate_title),
    ).ratio()
    artist_score = 0.5
    if expected_artist.strip() and candidate_artist.strip():
        artist_score = SequenceMatcher(
            None,
            _normalize_text_with_spaces(expected_artist),
            _normalize_text_with_spaces(candidate_artist),
        ).ratio()
    score = (title_score * 0.7) + (artist_score * 0.3)
    if expected_duration_seconds and candidate_duration_seconds:
        delta = abs(expected_duration_seconds - candidate_duration_seconds)
        if delta <= 2.0:
            score += 0.08
        elif delta <= 8.0:
            score += 0.03
        elif delta > 20.0:
            score -= 0.08
    return max(0.0, min(1.0, score))


def _extract_beatport_next_data(text: str) -> dict[str, Any] | None:
    match = re.search(r'__NEXT_DATA__"[^>]*>(.*?)</script>', text, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def _fetch_apple_music_metadata(
    *,
    title: str,
    artist: str,
    duration_seconds: float | None,
) -> dict[str, Any] | None:
    query = urllib.parse.quote(" ".join(part for part in (artist, title) if part).strip())
    payload = _request_json(f"https://itunes.apple.com/search?term={query}&entity=song&limit=10")
    results = payload.get("results", []) if isinstance(payload, dict) else []
    best_match: tuple[float, dict[str, Any]] | None = None
    for result in results:
        if not isinstance(result, dict):
            continue
        score = _score_match(
            expected_title=title,
            expected_artist=artist,
            candidate_title=str(result.get("trackName") or ""),
            candidate_artist=str(result.get("artistName") or ""),
            expected_duration_seconds=duration_seconds,
            candidate_duration_seconds=_safe_float(result.get("trackTimeMillis")) / 1000.0
            if _safe_float(result.get("trackTimeMillis")) is not None
            else None,
        )
        if best_match is None or score > best_match[0]:
            best_match = (score, result)
    if best_match is None or best_match[0] < 0.6:
        return None
    result = best_match[1]
    return {
        "source": "apple_music",
        "confidence": round(best_match[0], 3),
        "track_title": result.get("trackName") or title,
        "track_artist": result.get("artistName") or artist,
        "collection_name": result.get("collectionName") or "",
        "track_url": result.get("trackViewUrl") or "",
        "collection_url": result.get("collectionViewUrl") or "",
        "release_date": str(result.get("releaseDate") or "")[:10],
        "genre_primary": result.get("primaryGenreName") or "",
        "duration_seconds": round((_safe_float(result.get("trackTimeMillis")) or 0.0) / 1000.0, 3),
    }


def _fetch_beatport_metadata(
    *,
    title: str,
    artist: str,
    duration_seconds: float | None,
) -> dict[str, Any] | None:
    query = urllib.parse.quote(" ".join(part for part in (artist, title) if part).strip())
    text = _request_text(f"https://www.beatport.com/search/tracks?q={query}")
    next_data = _extract_beatport_next_data(text)
    if next_data is None:
        return None
    try:
        results = next_data["props"]["pageProps"]["dehydratedState"]["queries"][0]["state"]["data"]["data"]
    except (KeyError, IndexError, TypeError):
        return None
    best_match: tuple[float, dict[str, Any]] | None = None
    for result in results:
        if not isinstance(result, dict):
            continue
        artist_names = ", ".join(
            str(item.get("artist_name") or "").strip()
            for item in result.get("artists", [])
            if isinstance(item, dict)
        )
        mix_name = str(result.get("mix_name") or "")
        score = _score_match(
            expected_title=title,
            expected_artist=artist,
            candidate_title=str(result.get("track_name") or ""),
            candidate_artist=artist_names,
            expected_duration_seconds=duration_seconds,
            candidate_duration_seconds=_safe_duration_seconds(result.get("length")),
        )
        if "remix" in mix_name.lower() and "remix" not in title.lower():
            score -= 0.08
        if best_match is None or score > best_match[0]:
            best_match = (score, result)
    if best_match is None or best_match[0] < 0.6:
        return None
    result = best_match[1]
    track_title = str(result.get("track_name") or title).strip()
    mix_name = str(result.get("mix_name") or "").strip()
    url_slug = _slugify(f"{track_title} {mix_name}".strip()) or _slugify(track_title)
    genres = [
        str(item.get("genre_name") or "").strip()
        for item in result.get("genre", [])
        if isinstance(item, dict) and str(item.get("genre_name") or "").strip()
    ]
    remixers = [
        str(item.get("artist_name") or "").strip()
        for item in result.get("remixers") or []
        if isinstance(item, dict) and str(item.get("artist_name") or "").strip()
    ]
    artist_names = [
        str(item.get("artist_name") or "").strip()
        for item in result.get("artists", [])
        if isinstance(item, dict) and str(item.get("artist_name") or "").strip()
    ]
    label = ""
    if isinstance(result.get("label"), dict):
        label = str(result["label"].get("label_name") or "")
    release_name = ""
    if isinstance(result.get("release"), dict):
        release_name = str(result["release"].get("release_name") or "")
    return {
        "source": "beatport",
        "confidence": round(best_match[0], 3),
        "track_title": track_title,
        "track_artist": ", ".join(artist_names),
        "mix_name": mix_name,
        "track_url": f"https://www.beatport.com/track/{url_slug}/{result.get('track_id')}",
        "genre_primary": genres[0] if genres else "",
        "genre_secondary": genres[1:],
        "label": label,
        "release_name": release_name,
        "release_date": str(result.get("release_date") or "")[:10],
        "bpm": _safe_float(result.get("bpm")),
        "duration_seconds": _safe_duration_seconds(result.get("length")),
        "remixers": remixers,
    }


def _fetch_bandcamp_metadata(
    *,
    title: str,
    artist: str,
) -> dict[str, Any] | None:
    query = urllib.parse.quote(" ".join(part for part in (artist, title) if part).strip())
    text = _request_text(f"https://bandcamp.com/search?q={query}")
    matches = re.findall(
        r'<li class="searchresult.*?<a class="artcont" href="([^"]+)".*?<div class="itemtype">\s*([^<]+)\s*</div>.*?<div class="heading">\s*<a[^>]+>(.*?)</a>.*?<div class="subhead">\s*by\s*(.*?)\s*</div>',
        text,
        re.S | re.I,
    )
    best_match: tuple[float, tuple[str, str, str, str]] | None = None
    for href, item_type, heading, subhead in matches:
        score = _score_match(
            expected_title=title,
            expected_artist=artist,
            candidate_title=html.unescape(re.sub(r"<[^>]+>", "", heading)),
            candidate_artist=html.unescape(re.sub(r"<[^>]+>", "", subhead)),
        )
        if best_match is None or score > best_match[0]:
            best_match = (score, (href, item_type, heading, subhead))
    if best_match is None or best_match[0] < 0.55:
        return None
    href, item_type, _, _ = best_match[1]
    page_url = html.unescape(href).replace("&amp;", "&")
    page_text = _request_text(page_url)
    og_title_match = re.search(r'<meta property="og:title" content="([^"]+)"', page_text, re.I)
    description_match = re.search(r'<meta name="description" content="([^"]+)"', page_text, re.I)
    tags = [
        html.unescape(tag).strip()
        for tag in re.findall(r'<a class="tag"[^>]*>([^<]+)</a>', page_text, re.I)
        if html.unescape(tag).strip()
    ]
    release_date_match = re.search(r"released ([A-Za-z0-9 ,]+)", page_text, re.I)
    editorial_description = html.unescape(description_match.group(1)).strip() if description_match else ""
    editorial_description = re.sub(r"\s+", " ", editorial_description)
    return {
        "source": "bandcamp",
        "confidence": round(best_match[0], 3),
        "item_type": item_type.strip().lower(),
        "page_url": page_url,
        "og_title": html.unescape(og_title_match.group(1)).strip() if og_title_match else "",
        "release_date_text": release_date_match.group(1).strip() if release_date_match else "",
        "editorial_description": editorial_description,
        "tags": tags,
    }


def _collect_descriptors(*values: str) -> list[str]:
    descriptor_words = {
        "uplifting",
        "groovy",
        "groovier",
        "nostalgic",
        "melodic",
        "progressive",
        "cinematic",
        "dark",
        "darker",
        "tough",
        "house",
        "tech",
        "techno",
        "indie",
    }
    found: list[str] = []
    for value in values:
        normalized = _normalize_text_with_spaces(value)
        for word in descriptor_words:
            if word in normalized and word not in found:
                found.append(word)
    return found


def _derive_style_bias(summary: dict[str, Any]) -> dict[str, float]:
    genre_text = " ".join(
        [
            str(summary.get("genre_primary") or ""),
            *[str(item) for item in summary.get("genre_secondary", [])],
            *[str(item) for item in summary.get("tags", [])],
            *[str(item) for item in summary.get("editorial_descriptors", [])],
        ]
    ).lower()
    bias = {
        "progressive_patience": 0.45,
        "melodic_emphasis": 0.45,
        "groove_drive": 0.45,
        "euphoria": 0.4,
        "darkness": 0.25,
    }
    if "progressive house" in genre_text:
        bias["progressive_patience"] += 0.35
        bias["melodic_emphasis"] += 0.15
    if "melodic house" in genre_text or "melodic house & techno" in genre_text:
        bias["melodic_emphasis"] += 0.3
        bias["progressive_patience"] += 0.15
        bias["euphoria"] += 0.1
    if "tech house" in genre_text or "house" in genre_text:
        bias["groove_drive"] += 0.15
    if "indie dance" in genre_text:
        bias["darkness"] += 0.1
    if "uplifting" in genre_text:
        bias["euphoria"] += 0.2
    if "nostalgic" in genre_text:
        bias["melodic_emphasis"] += 0.1
    if "groovy" in genre_text or "groovier" in genre_text:
        bias["groove_drive"] += 0.15
    if "dark" in genre_text or "darker" in genre_text or "tough" in genre_text:
        bias["darkness"] += 0.2
    return {key: round(max(0.0, min(1.0, value)), 3) for key, value in bias.items()}


def fetch_web_enrichment(
    *,
    title: str,
    artist: str = "",
    duration_seconds: float | None = None,
) -> dict[str, Any]:
    """Fetch optional web metadata that can bias offline show generation."""
    providers: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}

    for provider_name, loader in (
        (
            "apple_music",
            lambda: _fetch_apple_music_metadata(
                title=title,
                artist=artist,
                duration_seconds=duration_seconds,
            ),
        ),
        (
            "beatport",
            lambda: _fetch_beatport_metadata(
                title=title,
                artist=artist,
                duration_seconds=duration_seconds,
            ),
        ),
        (
            "bandcamp",
            lambda: _fetch_bandcamp_metadata(
                title=title,
                artist=artist,
            ),
        ),
    ):
        try:
            record = loader()
        except (TimeoutError, OSError, ValueError, json.JSONDecodeError, urllib_error.URLError) as exc:
            errors[provider_name] = str(exc)
            continue
        if record:
            providers[provider_name] = record

    summary: dict[str, Any] = {
        "genre_primary": "",
        "genre_secondary": [],
        "label": "",
        "release_date": "",
        "mix_name": "",
        "remixers": [],
        "tags": [],
        "editorial_descriptors": [],
    }

    beatport = providers.get("beatport", {})
    apple_music = providers.get("apple_music", {})
    bandcamp = providers.get("bandcamp", {})
    summary["genre_primary"] = (
        str(beatport.get("genre_primary") or apple_music.get("genre_primary") or "")
    )
    summary["genre_secondary"] = list(beatport.get("genre_secondary") or [])
    summary["label"] = str(beatport.get("label") or "")
    summary["release_date"] = str(beatport.get("release_date") or apple_music.get("release_date") or "")
    summary["mix_name"] = str(beatport.get("mix_name") or "")
    summary["remixers"] = list(beatport.get("remixers") or [])
    summary["tags"] = list(bandcamp.get("tags") or [])
    summary["editorial_descriptors"] = _collect_descriptors(
        summary["genre_primary"],
        " ".join(summary["genre_secondary"]),
        " ".join(summary["tags"]),
        str(bandcamp.get("editorial_description") or ""),
    )
    summary["style_bias"] = _derive_style_bias(summary)

    confidence = {
        provider_name: float(record.get("confidence") or 0.0)
        for provider_name, record in providers.items()
    }
    max_confidence = max(confidence.values(), default=0.0)

    return {
        "version": _WEB_ENRICHMENT_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "query": {
            "title": title,
            "artist": artist,
            "duration_seconds": round(float(duration_seconds), 3) if duration_seconds else None,
        },
        "providers": providers,
        "summary": summary,
        "confidence": {
            "providers": confidence,
            "overall": round(max_confidence, 3),
        },
        "errors": errors,
    }
