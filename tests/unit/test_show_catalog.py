from __future__ import annotations

from click.testing import CliRunner

import photonic_synesthesia.ui.cli as cli_module
from photonic_synesthesia.showplan import build_semantic_profile
from photonic_synesthesia.showplan.semantic_profile import metadata_confidence
from photonic_synesthesia.integrations.show_catalog import (
    list_show_catalog_paths,
    load_show_catalog,
    save_show_catalog,
    show_catalog_path,
)
from photonic_synesthesia.integrations.show_plans import save_show_plan
from photonic_synesthesia.ui.cli import _load_precomputed_show_plan, cli


def test_showplan_build_semantic_profile_returns_expected_shape() -> None:
    profile = build_semantic_profile(
        track_title="Song",
        track_artist="Artist",
        duration_seconds=120.0,
        structure_markers=[{"name": "Intro", "kind": "intro", "start_seconds": 0.0, "energy_hint": 5}],
        rekordbox_average_bpm=122.0,
        web_enrichment={"summary": {"genre_primary": "Progressive House"}, "confidence": {"overall": 0.9}},
    )

    assert profile["version"] == 1
    assert profile["track_identity"]["tempo_band"] == "midtempo_club"
    assert profile["genre_hints"] == ["Progressive House"]


def test_showplan_metadata_confidence_prefers_rekordbox_match() -> None:
    confidence = metadata_confidence(
        structure_markers=[{"name": "Intro", "kind": "intro", "start_seconds": 0.0}],
        metadata_source="rekordbox_export",
        rekordbox_track_id="abc123",
        rekordbox_average_bpm=122.0,
        web_enrichment={"confidence": {"overall": 0.8}},
        matched_rekordbox_track=True,
    )

    assert confidence["track_match_confidence"] == 0.96
    assert confidence["beatgrid_confidence"] == 0.94
    assert confidence["confidence_tier"] in {"strict", "beat_safe"}


def test_show_catalog_round_trips(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    saved_path = save_show_catalog("Artist|Song", {"track_key": "Artist|Song", "show_sections": []})
    loaded = load_show_catalog("Artist|Song")

    assert saved_path == show_catalog_path("Artist|Song")
    assert loaded is not None
    assert loaded["track_key"] == "Artist|Song"
    assert list_show_catalog_paths() == [saved_path]


def test_precomputed_show_plan_prefers_editable_show_plan_over_catalog(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    save_show_catalog(
        "Artist|Song",
        {
            "track_key": "Artist|Song",
            "selection_mode": "ai_assisted",
            "show_sections": [{"id": "catalog"}],
        },
    )
    save_show_plan(
        "Artist|Song",
        {
            "track_key": "Artist|Song",
            "selection_mode": "procedural",
            "show_sections": [{"id": "show_plan"}],
        },
    )

    payload, source = _load_precomputed_show_plan("Artist|Song")

    assert source == "show_plan"
    assert payload is not None
    assert payload["show_sections"][0]["id"] == "show_plan"


def test_precomputed_show_plan_falls_back_to_catalog_when_no_show_plan(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    save_show_catalog(
        "Artist|Song",
        {
            "track_key": "Artist|Song",
            "selection_mode": "ai_assisted",
            "selection_variance": 0.2,
            "structure_markers": [{"name": "Intro", "kind": "intro", "start_seconds": 0.0}],
            "show_sections": [{"id": "catalog"}],
        },
    )

    payload, source = _load_precomputed_show_plan("Artist|Song")

    assert source == "catalog"
    assert payload is not None
    assert payload["show_sections"][0]["id"] == "catalog"
    assert payload["structure_markers"][0]["name"] == "Intro"
    assert payload["semantic_profile"] == {}


def test_catalog_build_command_writes_catalog_entries(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    audio_file = tmp_path / "Artist - Song.mp3"
    audio_file.write_bytes(b"fake")

    monkeypatch.setattr(cli_module, "_discover_rekordbox_xml", lambda: None)
    monkeypatch.setattr(cli_module, "_audio_file_duration_seconds", lambda _: 123.4)
    monkeypatch.setattr(
        cli_module,
        "_fetch_catalog_web_enrichment",
        lambda **_: {"version": 1, "summary": {"genre_primary": "Progressive House"}},
    )

    result = CliRunner().invoke(
        cli,
        ["catalog", "build", str(tmp_path), "--selection-mode", "procedural", "--selection-variance", "0.0"],
    )

    assert result.exit_code == 0
    catalog = load_show_catalog("Artist - Song")
    assert catalog is not None
    assert catalog["track_key"] == "Artist - Song"
    assert catalog["duration_seconds"] == 123.4
    assert isinstance(catalog["show_sections"], list)
    assert catalog["catalog_version"] == 7
    assert catalog["venue_mode"] == "small_room_50_100"
    assert catalog["metadata_confidence"]["confidence_tier"] == "degraded"
    assert catalog["metadata_confidence"]["source_precedence"] == [
        "rekordbox_edited_markers",
        "rekordbox_track_match",
        "beatgrid_transport",
        "audio_fallback",
        "web_enrichment",
    ]
    assert catalog["semantic_profile"]["version"] == 1
    assert catalog["semantic_profile"]["genre_hints"] == ["Progressive House"]
    assert catalog["show_sections"][0]["cue_recipe"]["version"] == 6
    assert catalog["show_sections"][0]["section_role"] == "intro"
    assert catalog["show_sections"][0]["cue_family_id"] == "small_room_50_100::intro::wash"
    assert catalog["show_sections"][0]["fixture_capability_graph"]["laser"]["allowed_geometries"]["intro"]
    assert catalog["show_sections"][0]["motif_ids"]
    assert catalog["show_sections"][0]["cue_recipe"]["trigger_policy"]["confidence_tier"] == "degraded"
    assert catalog["web_enrichment"]["summary"]["genre_primary"] == "Progressive House"
    assert catalog["motif_registry"]["current_motifs"]
    assert catalog["show_fingerprint"]["hash"]
    assert catalog["anti_template_validation"]["status"] in {"pass", "warn", "fail"}
    assert "aggregate" in catalog["scorer_bundle"]
    assert catalog["preview_artifacts"]["summary"]["section_stills"] >= 1
    assert catalog["model_payload"]["planner"]["genre_primary"] == "Progressive House"
    assert catalog["model_payload"]["planner"]["semantic_profile"]["genre_hints"] == ["Progressive House"]
    assert catalog["model_payload"]["planner"]["venue_profile"]["mode"] == "small_room_50_100"
    assert catalog["model_payload"]["planner"]["metadata_confidence"]["confidence_tier"] == "degraded"
    assert catalog["model_payload"]["planner"]["motif_registry"]["current_motifs"]
    assert catalog["model_payload"]["planner"]["show_fingerprint"]["hash"]
    assert catalog["model_payload"]["planner"]["anti_template_validation"]["status"] in {"pass", "warn", "fail"}
    assert "aggregate" in catalog["model_payload"]["planner"]["scorer_bundle"]
    assert catalog["model_payload"]["planner"]["preview_artifacts"]["summary"]["section_stills"] >= 1
    assert isinstance(catalog["model_payload"]["sections"], list)
    assert catalog["model_payload"]["sections"][0]["venue_mode"] == "small_room_50_100"
    assert catalog["model_payload"]["sections"][0]["cue_family_id"] == "small_room_50_100::intro::wash"
    assert catalog["model_payload"]["sections"][0]["fixture_capability_graph"]["laser"]["allowed_geometries"]["intro"]
    assert catalog["model_payload"]["sections"][0]["recipe_bundle"]["cue_family_id"] == "small_room_50_100::intro::wash"
    assert catalog["model_payload"]["sections"][0]["phaser_bundle"]
    assert catalog["model_payload"]["sections"][0]["trigger_policy"]["confidence_tier"] == "degraded"
    assert catalog["model_payload"]["sections"][0]["motif_ids"]
    assert catalog["model_payload"]["sections"][0]["candidates"]["laser"]
    assert catalog["model_payload"]["sections"][0]["current_selection"]["laser"]


def test_catalog_build_command_accepts_ollama_model_override(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    audio_file = tmp_path / "Artist - Song.mp3"
    audio_file.write_bytes(b"fake")

    captured: dict[str, str] = {}
    monkeypatch.setattr(cli_module, "_discover_rekordbox_xml", lambda: None)
    monkeypatch.setattr(cli_module, "_audio_file_duration_seconds", lambda _: 123.4)

    def _fake_build_show_catalog_entry(**kwargs):
        captured["model"] = cli_module._ollama_model_name()
        captured["host"] = cli_module._ollama_host()
        captured["endpoint"] = cli_module._ollama_generate_endpoint()
        captured["num_gpu"] = str(cli_module._ollama_num_gpu_option())
        return {
            "track_key": kwargs["track_key"],
            "track_title": kwargs["track_title"],
            "track_artist": kwargs["track_artist"],
            "duration_seconds": kwargs["duration_seconds"],
            "show_sections": [],
            "provenance": {"ollama_model": captured["model"]},
        }

    monkeypatch.setattr(cli_module, "_build_show_catalog_entry", _fake_build_show_catalog_entry)
    monkeypatch.setattr(cli_module, "_fetch_catalog_web_enrichment", lambda **_: {})

    result = CliRunner().invoke(
        cli,
        [
            "catalog",
            "build",
            str(tmp_path),
            "--selection-mode",
            "local_ollama_cpu",
            "--ollama-model",
            "qwen2.5:7b",
            "--ollama-host",
            "http://127.0.0.1:11500",
            "--ollama-use-gpu",
            "--limit",
            "1",
        ],
    )

    assert result.exit_code == 0
    assert captured["model"] == "qwen2.5:7b"
    assert captured["host"] == "http://127.0.0.1:11500"
    assert captured["endpoint"] == "http://127.0.0.1:11500/api/generate"
    assert captured["num_gpu"] == "None"


def test_catalog_build_command_can_disable_web_enrichment(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    audio_file = tmp_path / "Artist - Song.mp3"
    audio_file.write_bytes(b"fake")

    called: dict[str, bool] = {"value": False}
    monkeypatch.setattr(cli_module, "_discover_rekordbox_xml", lambda: None)
    monkeypatch.setattr(cli_module, "_audio_file_duration_seconds", lambda _: 123.4)

    def _fake_fetch(**kwargs):
        called["value"] = True
        return {"version": 1}

    monkeypatch.setattr(cli_module, "_fetch_catalog_web_enrichment", _fake_fetch)

    result = CliRunner().invoke(
        cli,
        [
            "catalog",
            "build",
            str(tmp_path),
            "--selection-mode",
            "procedural",
            "--no-web-enrichment",
            "--limit",
            "1",
        ],
    )

    assert result.exit_code == 0
    assert called["value"] is False


def test_catalog_export_model_payloads_writes_jsonl(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save_show_catalog(
        "Artist|Song",
        {
            "track_key": "Artist|Song",
            "model_payload": {"track": {"track_key": "Artist|Song"}, "sections": [], "planner": {}, "version": 1},
            "show_sections": [],
        },
    )
    save_show_catalog(
        "Artist|Other",
        {
            "track_key": "Artist|Other",
            "model_payload": {"track": {"track_key": "Artist|Other"}, "sections": [], "planner": {}, "version": 1},
            "show_sections": [],
        },
    )

    output_path = tmp_path / "payloads.jsonl"
    result = CliRunner().invoke(
        cli,
        ["catalog", "export-model-payloads", str(output_path), "--track-key", "Artist|Song"],
    )

    assert result.exit_code == 0
    exported = output_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(exported) == 1
    assert "Artist|Song" in exported[0]


def test_catalog_model_payload_includes_selected_patterns_in_candidates() -> None:
    markers = [
        {"name": "Intro", "kind": "intro", "start_seconds": 0.0, "energy_hint": 5},
        {"name": "Build", "kind": "build", "start_seconds": 64.0, "energy_hint": 6},
        {"name": "Drop", "kind": "drop", "start_seconds": 96.0, "energy_hint": 8},
    ]
    show_sections = cli_module._default_show_sections(
        markers,
        140.0,
        track_seed="artist|song",
        selection_mode="procedural",
        selection_variance=0.2,
        venue_mode="medium_room_150_400",
    )

    payload = cli_module._build_catalog_model_payload(
        track_key="artist|song",
        track_title="Song",
        track_artist="Artist",
        duration_seconds=140.0,
        structure_markers=markers,
        show_sections=show_sections,
        selection_mode="procedural",
        selection_variance=0.2,
        venue_mode="medium_room_150_400",
        web_enrichment={"summary": {}},
    )

    assert payload["track"]["venue_mode"] == "medium_room_150_400"
    assert payload["planner"]["venue_profile"]["mode"] == "medium_room_150_400"
    for section in payload["sections"]:
        assert section["venue_mode"] == "medium_room_150_400"
        assert section["section_role"]
        assert section["transition_intent"]["type"]
        for family in ("laser", "mover", "wash", "led"):
            current = section["current_selection"][family]
            if current:
                assert current in section["candidates"][family]
