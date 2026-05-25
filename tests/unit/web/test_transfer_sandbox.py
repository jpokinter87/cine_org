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
