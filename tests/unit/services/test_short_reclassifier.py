"""Tests du service ShortReclassifier (P3 courts-métrages)."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel

from src.infrastructure.persistence.models import MovieModel
from src.services.short_reclassifier import ShortReclassifier


THRESHOLD_SECONDS = 900


@pytest.fixture
def session():
    """Session SQLite in-memory avec toutes les tables."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def video_dir(tmp_path: Path) -> Path:
    """Répertoire video factice."""
    vid = tmp_path / "video"
    vid.mkdir()
    return vid


@pytest.fixture
def storage_dir(tmp_path: Path) -> Path:
    """Répertoire storage factice avec un fichier cible."""
    sto = tmp_path / "storage"
    sto.mkdir()
    return sto


def _create_symlinked_movie(
    session: Session,
    video_dir: Path,
    storage_dir: Path,
    *,
    title: str,
    duration_seconds: int | None,
    collection_name: str | None,
    current_video_subpath: str,
    storage_subpath: str,
    is_short: bool = False,
) -> MovieModel:
    """Crée un fichier storage + symlink video pointant dessus + entrée DB."""
    storage_file = storage_dir / storage_subpath
    storage_file.parent.mkdir(parents=True, exist_ok=True)
    storage_file.touch()

    video_link = video_dir / current_video_subpath
    video_link.parent.mkdir(parents=True, exist_ok=True)
    video_link.symlink_to(storage_file)

    model = MovieModel(
        title=title,
        duration_seconds=duration_seconds,
        collection_name=collection_name,
        file_path=str(storage_file),
        symlink_path=str(video_link),
        is_short=is_short,
    )
    session.add(model)
    session.commit()
    session.refresh(model)
    return model


class TestFindCandidates:
    """Sélection des films à reclasser en court-métrage."""

    def test_short_under_animation_is_candidate(
        self, session, video_dir, storage_dir
    ) -> None:
        _create_symlinked_movie(
            session,
            video_dir,
            storage_dir,
            title="Hare-Way to the Stars",
            duration_seconds=420,
            collection_name="Looney Tunes",
            current_video_subpath="Films/Animation/H/Hare-Way.mkv",
            storage_subpath="Films/Animation/H/Hare-Way.mkv",
        )

        reclassifier = ShortReclassifier(
            session=session,
            video_dir=video_dir,
            threshold_seconds=THRESHOLD_SECONDS,
        )
        candidates = reclassifier.find_candidates()
        assert len(candidates) == 1
        cand = candidates[0]
        assert cand.new_symlink == (
            video_dir / "Films" / "Courts" / "Looney Tunes" / "Hare-Way.mkv"
        )

    def test_long_movie_is_not_candidate(self, session, video_dir, storage_dir) -> None:
        _create_symlinked_movie(
            session,
            video_dir,
            storage_dir,
            title="Heat",
            duration_seconds=7200,
            collection_name=None,
            current_video_subpath="Films/Action/H/Heat.mkv",
            storage_subpath="Films/Action/H/Heat.mkv",
        )
        reclassifier = ShortReclassifier(
            session=session,
            video_dir=video_dir,
            threshold_seconds=THRESHOLD_SECONDS,
        )
        assert reclassifier.find_candidates() == []

    def test_already_marked_short_at_correct_location_is_not_candidate(
        self, session, video_dir, storage_dir
    ) -> None:
        _create_symlinked_movie(
            session,
            video_dir,
            storage_dir,
            title="Déjà reclassé",
            duration_seconds=300,
            collection_name="Pixar",
            current_video_subpath="Films/Courts/Pixar/Lava.mkv",
            storage_subpath="Films/Animation/L/Lava.mkv",
            is_short=True,
        )
        reclassifier = ShortReclassifier(
            session=session,
            video_dir=video_dir,
            threshold_seconds=THRESHOLD_SECONDS,
        )
        assert reclassifier.find_candidates() == []

    def test_already_short_in_divers_with_new_local_collection_is_candidate(
        self, session, video_dir, storage_dir
    ) -> None:
        """Drift P4 : court déjà marqué is_short mais dans Films/Courts/Divers/.
        Quand on lui assigne une collection locale, find_candidates doit le
        repérer pour le déplacer vers Films/Courts/{collection}/."""
        from src.infrastructure.persistence.models import LocalCollectionModel

        # Crée la collection locale
        coll = LocalCollectionModel(name="Cartoons Hanna-Barbera")
        session.add(coll)
        session.commit()
        session.refresh(coll)

        # Court déjà sous Divers, marqué is_short, sans collection TMDB
        model = _create_symlinked_movie(
            session,
            video_dir,
            storage_dir,
            title="Tom Concerto",
            duration_seconds=420,
            collection_name=None,
            current_video_subpath="Films/Courts/Divers/Tom Concerto.mkv",
            storage_subpath="Films/Animation/T/Tom Concerto.mkv",
            is_short=True,
        )

        # Assigne la collection locale (l'utilisateur vient de le faire via UI/CLI)
        model.local_collection_id = coll.id
        session.add(model)
        session.commit()

        reclassifier = ShortReclassifier(
            session=session,
            video_dir=video_dir,
            threshold_seconds=THRESHOLD_SECONDS,
        )
        candidates = reclassifier.find_candidates()
        assert len(candidates) == 1
        assert candidates[0].new_symlink == (
            video_dir
            / "Films"
            / "Courts"
            / "Cartoons Hanna-Barbera"
            / "Tom Concerto.mkv"
        )

    def test_movie_under_series_dir_is_skipped(
        self, session, video_dir, storage_dir
    ) -> None:
        """Sanity : un court sous Séries/ reste SERIES (priorité chemin)."""
        _create_symlinked_movie(
            session,
            video_dir,
            storage_dir,
            title="Mini",
            duration_seconds=300,
            collection_name=None,
            current_video_subpath="Series/TV/M/Mini.mkv",
            storage_subpath="Series/TV/M/Mini.mkv",
        )
        reclassifier = ShortReclassifier(
            session=session,
            video_dir=video_dir,
            threshold_seconds=THRESHOLD_SECONDS,
        )
        assert reclassifier.find_candidates() == []

    def test_movie_without_symlink_is_skipped(
        self, session, video_dir, storage_dir
    ) -> None:
        model = MovieModel(
            title="Sans symlink",
            duration_seconds=300,
            collection_name="X",
            file_path=str(storage_dir / "x.mkv"),
            symlink_path=None,
        )
        session.add(model)
        session.commit()

        reclassifier = ShortReclassifier(
            session=session,
            video_dir=video_dir,
            threshold_seconds=THRESHOLD_SECONDS,
        )
        assert reclassifier.find_candidates() == []

    def test_movie_without_duration_is_skipped(
        self, session, video_dir, storage_dir
    ) -> None:
        _create_symlinked_movie(
            session,
            video_dir,
            storage_dir,
            title="Sans durée",
            duration_seconds=None,
            collection_name="X",
            current_video_subpath="Films/Drame/S/SansDuree.mkv",
            storage_subpath="Films/Drame/S/SansDuree.mkv",
        )
        reclassifier = ShortReclassifier(
            session=session,
            video_dir=video_dir,
            threshold_seconds=THRESHOLD_SECONDS,
        )
        assert reclassifier.find_candidates() == []


class TestApply:
    """Application de la reclassification : déplacement symlink + DB."""

    def test_apply_moves_symlink_and_marks_is_short(
        self, session, video_dir, storage_dir
    ) -> None:
        model = _create_symlinked_movie(
            session,
            video_dir,
            storage_dir,
            title="Hare-Way to the Stars",
            duration_seconds=420,
            collection_name="Looney Tunes",
            current_video_subpath="Films/Animation/H/Hare-Way.mkv",
            storage_subpath="Films/Animation/H/Hare-Way.mkv",
        )
        old_path = Path(model.symlink_path)
        storage_target = old_path.readlink()

        reclassifier = ShortReclassifier(
            session=session,
            video_dir=video_dir,
            threshold_seconds=THRESHOLD_SECONDS,
        )
        candidates = reclassifier.find_candidates()
        assert len(candidates) == 1

        result = reclassifier.apply(candidates[0])
        assert result.moved is True
        assert result.error is None

        # L'ancien symlink est supprimé
        assert not old_path.exists() and not old_path.is_symlink()
        # Le nouveau symlink pointe vers la même cible storage
        new_path = candidates[0].new_symlink
        assert new_path.is_symlink()
        assert new_path.readlink() == storage_target

        # DB mise à jour
        session.refresh(model)
        assert model.is_short is True
        assert model.symlink_path == str(new_path)

    def test_apply_refuses_when_destination_already_exists(
        self, session, video_dir, storage_dir
    ) -> None:
        model = _create_symlinked_movie(
            session,
            video_dir,
            storage_dir,
            title="Hare-Way",
            duration_seconds=420,
            collection_name="Looney Tunes",
            current_video_subpath="Films/Animation/H/Hare-Way.mkv",
            storage_subpath="Films/Animation/H/Hare-Way.mkv",
        )
        # Pré-créer un fichier existant à la destination
        clash = video_dir / "Films" / "Courts" / "Looney Tunes" / "Hare-Way.mkv"
        clash.parent.mkdir(parents=True, exist_ok=True)
        clash.touch()

        reclassifier = ShortReclassifier(
            session=session,
            video_dir=video_dir,
            threshold_seconds=THRESHOLD_SECONDS,
        )
        result = reclassifier.apply(reclassifier.find_candidates()[0])
        assert result.moved is False
        assert result.error is not None
        # L'ancien symlink reste en place
        assert Path(model.symlink_path).is_symlink()
        # is_short pas modifié
        session.refresh(model)
        assert model.is_short is False
