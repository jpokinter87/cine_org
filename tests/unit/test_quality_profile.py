"""Tests du profil de qualité cible d'une série.

Quand la complétude signale des épisodes manquants, la fiche doit indiquer
en quelle qualité les rechercher : celle du reste de la série (résolution,
codecs, langues), calculée sur les épisodes réellement détenus.
"""

import json

from src.infrastructure.persistence.models import EpisodeModel
from src.services.completeness.quality_profile import (
    build_quality_targets,
    compute_quality_profile,
)


def _ep(
    season=1,
    episode=1,
    resolution="1920x1080",
    video="x264",
    audio="AC3",
    languages=("fr", "en"),
    file_path="/s/ep.mkv",
):
    return EpisodeModel(
        series_id=1,
        season_number=season,
        episode_number=episode,
        title=f"e{episode}",
        resolution=resolution,
        codec_video=video,
        codec_audio=audio,
        languages_json=json.dumps(list(languages)) if languages else None,
        file_path=file_path,
    )


# --- Calcul du profil -----------------------------------------------------


def test_profile_from_homogeneous_episodes():
    """Une saison homogène donne exactement ses caractéristiques."""
    profile = compute_quality_profile([_ep(episode=i) for i in range(1, 10)], "Saison 01")
    assert profile.resolution == "1920x1080"
    assert profile.video_codec == "x264"
    assert profile.audio_codec == "AC3"
    assert profile.languages == ("en", "fr")
    assert profile.sample_size == 9
    assert profile.mixed is False


def test_profile_takes_the_dominant_value():
    """Une valeur minoritaire ne l'emporte pas sur la dominante."""
    episodes = [_ep(episode=i) for i in range(1, 9)]
    episodes.append(_ep(episode=9, resolution="1280x720", video="x265"))
    profile = compute_quality_profile(episodes, "Saison 01")
    assert profile.resolution == "1920x1080"
    assert profile.video_codec == "x264"


def test_profile_flags_heterogeneous_seasons():
    """Une dominante faible (moins des deux tiers) est signalée comme mixte."""
    episodes = [_ep(episode=i, resolution="1920x1080") for i in range(1, 4)]
    episodes += [_ep(episode=i, resolution="1280x720") for i in range(4, 7)]
    profile = compute_quality_profile(episodes, "Saison 01")
    assert profile.mixed is True


def test_profile_ignores_episodes_without_file():
    """Les lignes sans fichier ne décrivent aucune qualité détenue."""
    episodes = [
        _ep(episode=1),
        _ep(episode=2, resolution="1280x720", video="x265", file_path=None),
    ]
    profile = compute_quality_profile(episodes, "Saison 01")
    assert profile.resolution == "1920x1080"
    assert profile.sample_size == 1


def test_profile_ignores_missing_fields():
    """Un champ vide sur certains épisodes n'écrase pas la dominante."""
    episodes = [_ep(episode=1, video=None), _ep(episode=2, video="x264")]
    profile = compute_quality_profile(episodes, "Saison 01")
    assert profile.video_codec == "x264"


def test_empty_profile_when_nothing_known():
    """Sans aucune métadonnée exploitable, le profil est vide."""
    episodes = [
        _ep(episode=1, resolution=None, video=None, audio=None, languages=None)
    ]
    profile = compute_quality_profile(episodes, "Saison 01")
    assert profile.is_empty is True


def test_empty_profile_when_no_episode_at_all():
    """Aucun épisode détenu → profil vide, sans erreur."""
    assert compute_quality_profile([], "Saison 01").is_empty is True


# --- Cibles dérivées des manques ------------------------------------------


def test_targets_use_the_season_of_the_missing_episodes():
    """Le profil proposé est celui de la saison concernée, pas de la série."""
    episodes = [_ep(season=1, episode=i, resolution="1280x720", video="x264") for i in range(1, 6)]
    episodes += [_ep(season=2, episode=i, resolution="1920x1080", video="x265") for i in range(1, 5)]
    detail = {"missing_seasons": [], "missing_episodes": [{"season": 2, "episode": 5}]}

    targets = build_quality_targets(episodes, detail)

    assert len(targets) == 1
    assert targets[0].scope_label == "Saison 02"
    assert targets[0].resolution == "1920x1080"
    assert targets[0].video_codec == "x265"


def test_targets_one_entry_per_distinct_season_profile():
    """Deux saisons de qualité différente donnent deux cibles."""
    episodes = [_ep(season=1, episode=i, resolution="1280x720") for i in range(1, 6)]
    episodes += [_ep(season=2, episode=i, resolution="1920x1080") for i in range(1, 5)]
    detail = {
        "missing_seasons": [],
        "missing_episodes": [
            {"season": 1, "episode": 6},
            {"season": 2, "episode": 5},
        ],
    }

    targets = build_quality_targets(episodes, detail)

    assert [t.scope_label for t in targets] == ["Saison 01", "Saison 02"]


def test_targets_collapse_when_all_seasons_match():
    """Des saisons de même qualité sont résumées en une seule cible."""
    episodes = [_ep(season=s, episode=i) for s in (1, 2) for i in range(1, 6)]
    detail = {
        "missing_seasons": [],
        "missing_episodes": [
            {"season": 1, "episode": 6},
            {"season": 2, "episode": 6},
        ],
    }

    targets = build_quality_targets(episodes, detail)

    assert len(targets) == 1
    assert targets[0].scope_label == "Série"


def test_targets_fall_back_to_series_for_a_season_without_data():
    """Une saison sans métadonnées emprunte le profil de la série."""
    episodes = [_ep(season=2, episode=i) for i in range(1, 6)]
    episodes += [
        _ep(season=1, episode=i, resolution=None, video=None, audio=None, languages=None)
        for i in range(1, 4)
    ]
    detail = {"missing_seasons": [], "missing_episodes": [{"season": 1, "episode": 4}]}

    targets = build_quality_targets(episodes, detail)

    assert len(targets) == 1
    assert targets[0].resolution == "1920x1080"


def test_targets_cover_entirely_missing_seasons():
    """Une saison entièrement absente reçoit le profil de la série."""
    episodes = [_ep(season=1, episode=i) for i in range(1, 6)]
    detail = {"missing_seasons": [2], "missing_episodes": []}

    targets = build_quality_targets(episodes, detail)

    assert len(targets) == 1
    assert targets[0].resolution == "1920x1080"


def test_no_targets_when_nothing_is_missing():
    """Série complète : aucune cible à proposer."""
    episodes = [_ep(episode=i) for i in range(1, 6)]
    assert build_quality_targets(episodes, {"missing_seasons": [], "missing_episodes": []}) == []


def test_no_targets_without_any_metadata():
    """Sans métadonnée exploitable, aucune cible n'est affichée."""
    episodes = [
        _ep(episode=i, resolution=None, video=None, audio=None, languages=None)
        for i in range(1, 4)
    ]
    detail = {"missing_seasons": [], "missing_episodes": [{"season": 1, "episode": 4}]}
    assert build_quality_targets(episodes, detail) == []


def test_no_targets_without_detail():
    """Détail de complétude absent (jamais vérifiée) : pas de cible."""
    assert build_quality_targets([_ep()], None) == []
