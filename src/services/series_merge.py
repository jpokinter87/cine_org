"""Service de fusion de deux fiches séries dupliquées en une seule.

Réunifie la série via les symlinks `video/` (jamais le storage physique),
conformément aux invariants d'ingestion du projet.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from src.core.value_objects.media_info import (
    AudioCodec,
    Language,
    MediaInfo,
    Resolution,
    VideoCodec,
)
from src.infrastructure.persistence.models import EpisodeModel


@dataclass
class EpisodeConflict:
    """Épisode présent dans les deux fiches (même saison/numéro)."""

    season_number: int
    episode_number: int
    recipient_episode_id: int
    absorbed_episode_id: int
    kept: str  # "recipient" | "absorbed"


@dataclass
class MergePreview:
    """Aperçu calculé d'une fusion, sans aucune mutation."""

    recipient_id: int
    absorbed_id: int
    recipient_title: str
    absorbed_title: str
    episodes_to_attach: int
    conflicts: list[EpisodeConflict] = field(default_factory=list)
    metadata_completed: dict[str, object] = field(default_factory=dict)
    target_series_folder: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass
class MergeResult:
    """Résultat d'une fusion effectuée."""

    recipient_id: int
    episodes_attached: int
    conflicts_resolved: int
    symlinks_regenerated: int
    absorbed_archived: bool


def build_media_info_from_episode(model: EpisodeModel) -> MediaInfo:
    """Reconstruit un MediaInfo depuis les colonnes techniques d'un EpisodeModel.

    Réplique le pattern de `video_file_repository._to_entity`. La résolution est
    stockée à plat (« 1920x1080 ») et reparsée en Resolution(width, height).
    """
    resolution = None
    if model.resolution and "x" in model.resolution:
        parts = model.resolution.split("x")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            resolution = Resolution(width=int(parts[0]), height=int(parts[1]))

    video_codec = VideoCodec(name=model.codec_video) if model.codec_video else None

    audio_codecs: tuple[AudioCodec, ...] = ()
    if model.codec_audio:
        audio_codecs = (AudioCodec(name=model.codec_audio),)

    audio_languages: tuple[Language, ...] = ()
    if model.languages_json:
        codes = json.loads(model.languages_json)
        audio_languages = tuple(Language(code=code, name=code) for code in codes)

    return MediaInfo(
        resolution=resolution,
        video_codec=video_codec,
        audio_codecs=audio_codecs,
        audio_languages=audio_languages,
        duration_seconds=model.duration_seconds,
    )
