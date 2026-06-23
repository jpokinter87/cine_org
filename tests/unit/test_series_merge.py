import json

import pytest
from sqlmodel import SQLModel, Session, create_engine

from src.core.value_objects.media_info import MediaInfo
from src.infrastructure.persistence.models import EpisodeModel, SeriesModel
from src.infrastructure.persistence.repositories.series_repository import SQLModelSeriesRepository
from src.infrastructure.persistence.repositories.episode_repository import SQLModelEpisodeRepository
from src.services.duplicate_detector import DuplicateDetector
from src.services.series_merge import build_media_info_from_episode, SeriesMergeService


def _episode_model(**kw):
    defaults = dict(
        series_id=1,
        season_number=1,
        episode_number=1,
        title="Ep",
        resolution="1920x1080",
        codec_video="x265",
        codec_audio="AAC",
        languages_json=json.dumps(["fr", "en"]),
        duration_seconds=2700,
    )
    defaults.update(kw)
    return EpisodeModel(**defaults)


def test_build_media_info_parses_resolution_and_codecs():
    info = build_media_info_from_episode(_episode_model())
    assert isinstance(info, MediaInfo)
    assert info.resolution.width == 1920
    assert info.resolution.height == 1080
    assert info.video_codec.name == "x265"
    assert info.audio_codecs[0].name == "AAC"
    assert {lang.code for lang in info.audio_languages} == {"fr", "en"}
    assert info.duration_seconds == 2700


def test_build_media_info_handles_missing_fields():
    info = build_media_info_from_episode(
        _episode_model(
            resolution=None,
            codec_video=None,
            codec_audio=None,
            languages_json=None,
        )
    )
    assert info.resolution is None
    assert info.video_codec is None
    assert info.audio_codecs == ()
    assert info.audio_languages == ()


from pathlib import Path

from src.services.series_merge import SeriesMergeService
from src.core.entities.media import Series, Episode
from src.adapters.file_system import FileSystemAdapter
from src.services.organizer import OrganizerService
from src.services.renamer import RenamerService


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _make_series(session, **kw):
    defaults = dict(title="Doctor Who", year=2005, tmdb_id=57243, genres_json='["Drama"]')
    defaults.update(kw)
    model = SeriesModel(**defaults)
    session.add(model)
    session.commit()
    session.refresh(model)
    return model


def _make_episode(session, series_id, season, ep, **kw):
    defaults = dict(
        title=f"E{ep}", resolution="1920x1080", codec_video="x265",
        codec_audio="AAC", languages_json='["fr"]', file_path=f"/storage/s{season}e{ep}.mkv",
    )
    defaults.update(kw)
    model = EpisodeModel(series_id=series_id, season_number=season, episode_number=ep, **defaults)
    session.add(model)
    session.commit()
    session.refresh(model)
    return model


def _service(session, tmp_path):
    return SeriesMergeService(
        session=session, video_dir=tmp_path / "video", file_system=FileSystemAdapter(),
        organizer=OrganizerService(), renamer=RenamerService(),
        duplicate_detector=DuplicateDetector(),
        series_repo=SQLModelSeriesRepository(session),
        episode_repo=SQLModelEpisodeRepository(session),
    )


def test_regenerate_symlink_creates_canonical_link(tmp_path):
    storage = tmp_path / "storage"
    video = tmp_path / "video"
    storage.mkdir()
    video.mkdir()
    source = storage / "Doctor Who S08E01.mkv"
    source.write_text("video-bytes")

    series = Series(id="1", title="Doctor Who", year=2005, genres=("Drama",))
    episode = Episode(
        id="10", series_id="1", season_number=8, episode_number=1, title="En apnée",
        file_path=str(source), resolution="1920x1080", codec_video="x265",
        codec_audio="AAC", languages=("fr", "en"),
    )

    svc = SeriesMergeService(
        session=None, video_dir=video, file_system=FileSystemAdapter(),
        organizer=OrganizerService(), renamer=RenamerService(),
        duplicate_detector=None, series_repo=None, episode_repo=None,
    )
    media_info = build_media_info_from_episode(_episode_model(
        season_number=8, episode_number=1, title="En apnée",
    ))
    new_link = svc.regenerate_symlink(series, episode, media_info, source)

    assert new_link.is_symlink()
    assert new_link.resolve() == source.resolve()
    assert "Doctor Who (2005)" in str(new_link)
    assert "Saison 08" in str(new_link)
    assert new_link.name.startswith("Doctor Who (2005) - S08E01")


def test_preview_counts_episodes_and_completes_metadata(session, tmp_path):
    recipient = _make_series(session, title="Doctor Who", tvdb_id=None, tmdb_id=57243)
    absorbed = _make_series(session, title="Doctor Who (2005)", tvdb_id=78804, tmdb_id=57243)
    _make_episode(session, recipient.id, 1, 1)
    _make_episode(session, absorbed.id, 8, 1)
    _make_episode(session, absorbed.id, 8, 2)

    preview = _service(session, tmp_path).preview(recipient.id, absorbed.id)

    assert preview.episodes_to_attach == 2
    assert preview.conflicts == []
    assert preview.metadata_completed.get("tvdb_id") == 78804
    assert preview.target_series_folder == "Doctor Who (2005)"
    assert preview.warnings == []


def test_preview_detects_conflict(session, tmp_path):
    recipient = _make_series(session)
    absorbed = _make_series(session, title="Doctor Who (2005)", tmdb_id=57243)
    _make_episode(session, recipient.id, 9, 6)
    _make_episode(session, absorbed.id, 9, 6)

    preview = _service(session, tmp_path).preview(recipient.id, absorbed.id)

    assert len(preview.conflicts) == 1
    assert preview.conflicts[0].season_number == 9
    assert preview.conflicts[0].episode_number == 6
    assert preview.episodes_to_attach == 0


def test_preview_warns_on_different_tmdb_and_year(session, tmp_path):
    recipient = _make_series(session, title="Doctor Who", year=2005, tmdb_id=57243)
    absorbed = _make_series(session, title="Doctor Who", year=2024, tmdb_id=239770)

    preview = _service(session, tmp_path).preview(recipient.id, absorbed.id)

    assert any("tmdb" in w.lower() for w in preview.warnings)
    assert any("année" in w.lower() for w in preview.warnings)


def test_merge_attaches_episodes_and_archives_absorbed(session, tmp_path):
    from src.infrastructure.persistence.models import SeriesModel, EpisodeModel, TrashModel
    storage = tmp_path / "storage"
    storage.mkdir()
    recipient = _make_series(session, title="Doctor Who", tvdb_id=None, tmdb_id=57243)
    absorbed = _make_series(session, title="Doctor Who (2005)", tvdb_id=78804, tmdb_id=57243)

    f_r = storage / "r_s01e01.mkv"; f_r.write_text("x")
    f_a = storage / "a_s08e01.mkv"; f_a.write_text("x")
    _make_episode(session, recipient.id, 1, 1, file_path=str(f_r))
    ep_a = _make_episode(session, absorbed.id, 8, 1, file_path=str(f_a))

    result = _service(session, tmp_path).merge(recipient.id, absorbed.id)

    assert result.episodes_attached == 1
    assert result.conflicts_resolved == 0
    assert result.absorbed_archived is True
    session.refresh(ep_a)
    assert ep_a.series_id == recipient.id
    session.refresh(recipient)
    assert recipient.tvdb_id == 78804
    assert session.get(SeriesModel, absorbed.id) is None
    from sqlmodel import select
    trashed = session.exec(
        select(TrashModel).where(TrashModel.entity_type == "series")
    ).all()
    assert any(t.original_id == absorbed.id for t in trashed)
    assert ep_a.symlink_path is not None
    assert "Doctor Who (2005)" in ep_a.symlink_path


def test_merge_keeps_best_quality_on_conflict(session, tmp_path):
    from src.infrastructure.persistence.models import EpisodeModel
    from sqlmodel import select
    storage = tmp_path / "storage"; storage.mkdir()
    recipient = _make_series(session, title="Doctor Who", tmdb_id=57243)
    absorbed = _make_series(session, title="Doctor Who (2005)", tmdb_id=57243)

    f_low = storage / "low.mkv"; f_low.write_text("x")
    f_high = storage / "high.mkv"; f_high.write_text("x")
    ep_r = _make_episode(session, recipient.id, 9, 6, file_path=str(f_low),
                         resolution="720x576", codec_video="x264")
    ep_a = _make_episode(session, absorbed.id, 9, 6, file_path=str(f_high),
                         resolution="1920x1080", codec_video="x265")

    result = _service(session, tmp_path).merge(recipient.id, absorbed.id)

    assert result.conflicts_resolved == 1
    remaining = session.exec(
        select(EpisodeModel).where(EpisodeModel.season_number == 9,
                                   EpisodeModel.episode_number == 6)
    ).all()
    assert len(remaining) == 1
    assert remaining[0].series_id == recipient.id
    assert remaining[0].resolution == "1920x1080"
    assert f_low.exists() and f_high.exists()
