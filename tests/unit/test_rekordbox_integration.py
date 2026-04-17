from pathlib import Path

from photonic_synesthesia.integrations import load_rekordbox_track


def test_load_rekordbox_track_matches_by_filename_and_dedupes_markers(tmp_path: Path) -> None:
    xml_path = tmp_path / "rekordbox.xml"
    xml_path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<DJ_PLAYLISTS Version="1.0.0">
  <PRODUCT Name="rekordbox" Version="7.2.8" Company="AlphaTheta" />
  <COLLECTION Entries="1">
    <TRACK TrackID="42" Name="Relax Your Mind" Artist="19_26, Yubik"
      Location="file://localhost/C:/Music/19%2026%20-%20Relax%20Your%20Mind.mp3"
      TotalTime="324" AverageBpm="124.0">
      <POSITION_MARK Name="Intro E:6" Type="0" Start="0.000" Num="0" />
      <POSITION_MARK Name="Build E:7" Type="0" Start="64.000" Num="1" />
      <POSITION_MARK Name="Drop E:8" Type="0" Start="128.000" Num="2" />
      <POSITION_MARK Name="Drop E:8" Type="0" Start="128.000" Num="-1" />
      <POSITION_MARK Name="Breakdown E:5" Type="0" Start="192.000" Num="3" />
      <POSITION_MARK Name="Outro E:6" Type="0" Start="256.000" Num="4" />
    </TRACK>
  </COLLECTION>
</DJ_PLAYLISTS>
""",
        encoding="utf-8",
    )

    track = load_rekordbox_track(xml_path, tmp_path / "19 26 - Relax Your Mind.mp3")

    assert track is not None
    assert track.title == "Relax Your Mind"
    assert track.artist == "19_26, Yubik"
    assert [marker.kind for marker in track.markers] == [
        "intro",
        "build",
        "drop",
        "breakdown",
        "outro",
    ]
    assert track.markers[2].energy_hint == 8


def test_load_rekordbox_track_uses_duration_to_break_filename_ties(tmp_path: Path) -> None:
    xml_path = tmp_path / "rekordbox.xml"
    xml_path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<DJ_PLAYLISTS Version="1.0.0">
  <COLLECTION Entries="2">
    <TRACK TrackID="42" Name="Relax Your Mind" Artist="19_26, Yubik"
      Location="file://localhost/C:/Music/Relax%20Your%20Mind.mp3"
      TotalTime="324" AverageBpm="124.0" />
    <TRACK TrackID="43" Name="Relax Your Mind (Edit)" Artist="19_26, Yubik"
      Location="file://localhost/C:/Music/Relax%20Your%20Mind.mp3"
      TotalTime="278" AverageBpm="124.0" />
  </COLLECTION>
</DJ_PLAYLISTS>
""",
        encoding="utf-8",
    )

    track = load_rekordbox_track(
        xml_path,
        tmp_path / "Relax Your Mind.mp3",
        audio_duration_seconds=323.5,
    )

    assert track is not None
    assert track.track_id == "42"


def test_load_rekordbox_track_returns_none_for_ambiguous_equal_matches(tmp_path: Path) -> None:
    xml_path = tmp_path / "rekordbox.xml"
    xml_path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<DJ_PLAYLISTS Version="1.0.0">
  <COLLECTION Entries="2">
    <TRACK TrackID="42" Name="Same Song" Artist="Artist A"
      Location="file://localhost/C:/Music/Same%20Song.mp3"
      TotalTime="324" AverageBpm="124.0" />
    <TRACK TrackID="43" Name="Same Song" Artist="Artist A"
      Location="file://localhost/C:/Alt/Same%20Song.mp3"
      TotalTime="324" AverageBpm="124.0" />
  </COLLECTION>
</DJ_PLAYLISTS>
""",
        encoding="utf-8",
    )

    track = load_rekordbox_track(xml_path, tmp_path / "Same Song.mp3")

    assert track is None
