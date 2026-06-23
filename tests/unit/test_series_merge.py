import json

import pytest

from src.core.value_objects.media_info import MediaInfo
from src.infrastructure.persistence.models import EpisodeModel
from src.services.series_merge import build_media_info_from_episode


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
