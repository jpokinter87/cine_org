"""Tests MissingFileResolver : recherche via les symlinks vivants de video/."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel

from src.infrastructure.persistence.models import MovieModel
from src.services.missing_file_resolver import MissingFileResolver
from src.services.missing_files_scanner import MissingRecord


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _record(
    stale_path: Path, *, entity_type: str = "movie", entity_id: int = 1
) -> MissingRecord:
    return MissingRecord(
        entity_type=entity_type,
        entity_id=entity_id,
        title=stale_path.stem,
        file_path=str(stale_path),
    )


def _setup_dirs(tmp_path: Path) -> tuple[Path, Path]:
    """Crée storage/ et video/ vides et les retourne."""
    storage = tmp_path / "storage"
    video = tmp_path / "video"
    storage.mkdir()
    video.mkdir()
    return storage, video


def _make_symlinked_file(
    storage: Path,
    video: Path,
    storage_subpath: str,
    video_subpath: str,
) -> tuple[Path, Path]:
    """Crée un fichier storage + un symlink video qui pointe dessus."""
    target = storage / storage_subpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch()
    link = video / video_subpath
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)
    return target, link


class TestResolverFindCandidates:
    """Recherche par basename dans les symlinks vivants de video_dir."""

    def test_finds_target_of_live_symlink(self, tmp_path: Path) -> None:
        storage, video = _setup_dirs(tmp_path)
        target, _link = _make_symlinked_file(
            storage,
            video,
            "Films/Drame/Et la fête continue ! (2024).mkv",
            "Films/Drame/Et la fête continue ! (2024).mkv",
        )

        stale = storage / "Films" / "Comédie" / "Et la fête continue ! (2024).mkv"
        rec = _record(stale)

        resolver = MissingFileResolver(video_dir=video)
        assert resolver.find_candidates(rec) == [target]

    def test_no_symlink_in_video_returns_empty(self, tmp_path: Path) -> None:
        """Un fichier dans storage mais sans symlink dans video → pas candidat."""
        storage, video = _setup_dirs(tmp_path)
        # Fichier présent dans storage mais aucun symlink créé
        f = storage / "Films" / "Drame" / "Solo.mkv"
        f.parent.mkdir(parents=True)
        f.touch()

        rec = _record(storage / "ailleurs" / "Solo.mkv")
        assert MissingFileResolver(video_dir=video).find_candidates(rec) == []

    def test_broken_symlink_is_ignored(self, tmp_path: Path) -> None:
        storage, video = _setup_dirs(tmp_path)
        link = video / "Films" / "Drame" / "Broken.mkv"
        link.parent.mkdir(parents=True)
        link.symlink_to(storage / "absent.mkv")  # cible inexistante → cassé

        rec = _record(storage / "ailleurs" / "Broken.mkv")
        assert MissingFileResolver(video_dir=video).find_candidates(rec) == []

    def test_multiple_symlinks_same_target_collapse_to_one(
        self, tmp_path: Path
    ) -> None:
        """Deux symlinks dans video pointant vers le même fichier → 1 seul candidat."""
        storage, video = _setup_dirs(tmp_path)
        target = storage / "Films" / "A.mkv"
        target.parent.mkdir(parents=True)
        target.touch()

        for sub in ("Films/Drame/A.mkv", "Films/Comédie/A.mkv"):
            link = video / sub
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(target)

        rec = _record(storage / "ailleurs" / "A.mkv")
        assert MissingFileResolver(video_dir=video).find_candidates(rec) == [target]

    def test_multiple_targets_returned_when_ambiguous(self, tmp_path: Path) -> None:
        """Deux symlinks même basename mais cibles différentes → ambigu (2 candidats)."""
        storage, video = _setup_dirs(tmp_path)
        t1 = storage / "Films" / "A" / "X.mkv"
        t2 = storage / "Films" / "B" / "X.mkv"
        for t in (t1, t2):
            t.parent.mkdir(parents=True, exist_ok=True)
            t.touch()
        (video / "Films" / "Drame").mkdir(parents=True)
        (video / "Films" / "Action").mkdir(parents=True)
        (video / "Films" / "Drame" / "X.mkv").symlink_to(t1)
        (video / "Films" / "Action" / "X.mkv").symlink_to(t2)

        rec = _record(storage / "ailleurs" / "X.mkv")
        cands = MissingFileResolver(video_dir=video).find_candidates(rec)
        assert set(cands) == {t1, t2}

    def test_video_dir_missing_returns_empty(self, tmp_path: Path) -> None:
        rec = _record(tmp_path / "Films" / "Solo.mkv")
        resolver = MissingFileResolver(video_dir=tmp_path / "inexistant")
        assert resolver.find_candidates(rec) == []


class TestApplyRepair:
    """Mise à jour de file_path en DB."""

    def test_apply_updates_movie_file_path(self, session, tmp_path: Path) -> None:
        new_path = tmp_path / "Films" / "Drame" / "Respire (2014).mkv"
        new_path.parent.mkdir(parents=True)
        new_path.touch()

        movie = MovieModel(
            title="Respire",
            year=2014,
            file_path=str(tmp_path / "Films" / "Comédie" / "Respire (2014).mkv"),
        )
        session.add(movie)
        session.commit()
        session.refresh(movie)

        rec = MissingRecord(
            entity_type="movie",
            entity_id=movie.id,
            title="Respire",
            file_path=movie.file_path,
        )
        ok = MissingFileResolver(video_dir=tmp_path).apply_repair(
            session, rec, new_path
        )

        assert ok is True
        session.refresh(movie)
        assert movie.file_path == str(new_path)

    def test_apply_unknown_entity_type_returns_false(
        self, session, tmp_path: Path
    ) -> None:
        rec = MissingRecord(
            entity_type="invalid",
            entity_id=1,
            title="?",
            file_path="/whatever",
        )
        ok = MissingFileResolver(video_dir=tmp_path).apply_repair(
            session, rec, tmp_path / "x.mkv"
        )
        assert ok is False
