from __future__ import annotations

import json

from photonic_synesthesia.integrations import web_enrichment as enrichment_module


def test_fetch_web_enrichment_merges_provider_metadata(monkeypatch) -> None:
    apple_payload = {
        "results": [
            {
                "trackName": "Starchaser",
                "artistName": "Tinlicker",
                "collectionName": "Starchaser - Single",
                "trackViewUrl": "https://music.apple.com/us/album/starchaser/1700319172?i=1700319179&uo=4",
                "collectionViewUrl": "https://music.apple.com/us/album/starchaser/1700319172",
                "releaseDate": "2023-08-25T07:00:00Z",
                "primaryGenreName": "Dance",
                "trackTimeMillis": 434000,
            }
        ]
    }
    beatport_payload = {
        "props": {
            "pageProps": {
                "dehydratedState": {
                    "queries": [
                        {
                            "state": {
                                "data": {
                                    "data": [
                                        {
                                            "track_id": 18330844,
                                            "track_name": "Starchaser",
                                            "mix_name": "Original Mix",
                                            "bpm": 124,
                                            "length": 434,
                                            "genre": [{"genre_name": "Progressive House"}],
                                            "artists": [{"artist_name": "Tinlicker"}],
                                            "label": {"label_name": "Global Underground"},
                                            "release": {"release_name": "Starchaser"},
                                            "release_date": "2023-08-25",
                                        }
                                    ]
                                }
                            }
                        }
                    ]
                }
            }
        }
    }
    bandcamp_search = """
    <li class="searchresult data-search">
      <a class="artcont" href="https://tinlicker.bandcamp.com/track/starchaser?from=search&amp;search_rank=1"></a>
      <div class="result-info">
        <div class="itemtype">TRACK</div>
        <div class="heading"><a href="#">Starchaser</a></div>
        <div class="subhead">by Tinlicker</div>
      </div>
    </li>
    """
    bandcamp_page = """
    <meta property="og:title" content="Starchaser, by Tinlicker">
    <meta name="description" content="Starchaser by Tinlicker, released August 25, 2023 uplifting melodic progressive grooves">
    <a class="tag">progressive house</a>
    <a class="tag">melodic</a>
    """

    def _fake_request_json(url: str):
        assert "itunes.apple.com/search" in url
        return apple_payload

    def _fake_request_text(url: str) -> str:
        if "beatport.com/search/tracks" in url:
            return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(beatport_payload)}</script>'
        if "bandcamp.com/search" in url:
            return bandcamp_search
        if "tinlicker.bandcamp.com/track/starchaser" in url:
            return bandcamp_page
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(enrichment_module, "_request_json", _fake_request_json)
    monkeypatch.setattr(enrichment_module, "_request_text", _fake_request_text)

    enrichment = enrichment_module.fetch_web_enrichment(
        title="Starchaser",
        artist="Tinlicker",
        duration_seconds=434.0,
    )

    assert enrichment["providers"]["beatport"]["genre_primary"] == "Progressive House"
    assert enrichment["providers"]["bandcamp"]["item_type"] == "track"
    assert enrichment["summary"]["label"] == "Global Underground"
    assert enrichment["summary"]["style_bias"]["progressive_patience"] > 0.7


def test_fetch_web_enrichment_tolerates_provider_errors(monkeypatch) -> None:
    def _raise_request(url: str):
        raise OSError("offline")

    monkeypatch.setattr(enrichment_module, "_request_json", lambda url: {"results": []})
    monkeypatch.setattr(enrichment_module, "_request_text", _raise_request)

    enrichment = enrichment_module.fetch_web_enrichment(
        title="Unknown",
        artist="",
        duration_seconds=None,
    )

    assert enrichment["providers"] == {}
    assert enrichment["confidence"]["overall"] == 0.0
    assert "beatport" in enrichment["errors"]
