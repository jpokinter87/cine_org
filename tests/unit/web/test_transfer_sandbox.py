"""Tests des opérations sandbox de la route transfert."""

from pathlib import Path

from src.web.routes.transfer import _sandbox_existing
from src.services.sandbox_service import REPLACED_SUBDIR


def test_sandbox_existing_movie_goes_to_replaced_subdir(tmp_path: Path):
    storage = tmp_path / "storage"
    video = tmp_path / "video"
    sandbox = tmp_path / ".sandbox"

    # Film existant dans storage + symlink dans video
    movie_storage = storage / "Films" / "SF" / "A-B" / "Alien (1979)"
    movie_storage.mkdir(parents=True)
    real = movie_storage / "Alien (1979) AV1.mkv"
    real.write_text("av1")

    movie_video = video / "Films" / "SF" / "A-B" / "Alien (1979)"
    movie_video.mkdir(parents=True)
    (movie_video / "Alien (1979) AV1.mkv").symlink_to(real)

    _sandbox_existing(movie_video, sandbox, storage, video)

    dest = sandbox / REPLACED_SUBDIR / "Films" / "SF" / "A-B" / "Alien (1979)"
    assert dest.exists()
    assert (dest / "Alien (1979) AV1.mkv").exists()
    assert not movie_storage.exists()


def test_sandbox_existing_series_episode_goes_to_replaced_subdir(tmp_path: Path):
    """Vérifie que seul l'épisode ciblé par episode_key est sandboxé (branche série)."""
    storage = tmp_path / "storage"
    video = tmp_path / "video"
    sandbox = tmp_path / ".sandbox"

    # Série existante : 2 épisodes dans storage + symlinks dans video
    season_storage = storage / "Series" / "O" / "Octobre (2021)" / "Saison 01"
    season_storage.mkdir(parents=True)
    ep1 = season_storage / "Octobre (2021) - S01E01 - AV1.mkv"
    ep2 = season_storage / "Octobre (2021) - S01E02 - AV1.mkv"
    ep1.write_text("av1-ep1")
    ep2.write_text("av1-ep2")

    series_video = video / "Series" / "O" / "Octobre (2021)"
    season_video = series_video / "Saison 01"
    season_video.mkdir(parents=True)
    (season_video / ep1.name).symlink_to(ep1)
    (season_video / ep2.name).symlink_to(ep2)

    _sandbox_existing(series_video, sandbox, storage, video, episode_key="S01E01")

    # Seul l'épisode S01E01 part sous anciennes_versions/
    dest1 = (
        sandbox / REPLACED_SUBDIR / "Series" / "O" / "Octobre (2021)"
        / "Saison 01" / ep1.name
    )
    assert dest1.exists()
    assert dest1.read_text() == "av1-ep1"
    # S01E01 retiré du storage et son symlink supprimé ; S01E02 intact
    assert not ep1.exists()
    assert ep2.exists()
    assert not (season_video / ep1.name).exists()
    assert (season_video / ep2.name).exists()
