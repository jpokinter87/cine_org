"""Tests pour les methodes get_by_symlink_path et update_symlink_path."""

from pathlib import Path


# ============================================================================
# Phase 2 : Repository
# ============================================================================


class TestRepositoryMethods:
    """Tests pour les methodes get_by_symlink_path et update_symlink_path."""

    def test_get_by_symlink_path_found(self):
        """get_by_symlink_path retourne le VideoFile quand il existe."""
        from sqlmodel import Session, SQLModel, create_engine, select
        from src.infrastructure.persistence.models import VideoFileModel
        from src.infrastructure.persistence.repositories.video_file_repository import (
            SQLModelVideoFileRepository,
        )

        engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)

        with Session(engine) as session:
            model = VideoFileModel(
                path="/storage/film.mkv",
                symlink_path="/video/Films/Action/film.mkv",
                filename="film.mkv",
                size_bytes=1000,
            )
            session.add(model)
            session.commit()

            repo = SQLModelVideoFileRepository(session)
            result = repo.get_by_symlink_path(Path("/video/Films/Action/film.mkv"))

            assert result is not None
            assert result.filename == "film.mkv"
            assert result.symlink_path == Path("/video/Films/Action/film.mkv")

    def test_get_by_symlink_path_not_found(self):
        """get_by_symlink_path retourne None quand inexistant."""
        from sqlmodel import Session, SQLModel, create_engine
        from src.infrastructure.persistence.repositories.video_file_repository import (
            SQLModelVideoFileRepository,
        )

        engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)

        with Session(engine) as session:
            repo = SQLModelVideoFileRepository(session)
            result = repo.get_by_symlink_path(Path("/video/Films/inexistant.mkv"))

            assert result is None

    def test_update_symlink_path(self):
        """update_symlink_path met a jour le chemin en BDD."""
        from sqlmodel import Session, SQLModel, create_engine, select
        from src.infrastructure.persistence.models import VideoFileModel
        from src.infrastructure.persistence.repositories.video_file_repository import (
            SQLModelVideoFileRepository,
        )

        engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)

        with Session(engine) as session:
            model = VideoFileModel(
                path="/storage/film.mkv",
                symlink_path="/video/Films/Drame/film.mkv",
                filename="film.mkv",
                size_bytes=1000,
            )
            session.add(model)
            session.commit()

            repo = SQLModelVideoFileRepository(session)
            result = repo.update_symlink_path(
                Path("/video/Films/Drame/film.mkv"),
                Path("/video/Films/Action/film.mkv"),
            )

            assert result is True

            # Verifier en BDD
            updated = session.exec(
                select(VideoFileModel).where(VideoFileModel.id == model.id)
            ).first()
            assert updated.symlink_path == "/video/Films/Action/film.mkv"

    def test_update_symlink_path_not_found(self):
        """update_symlink_path retourne False si le chemin n'existe pas."""
        from sqlmodel import Session, SQLModel, create_engine
        from src.infrastructure.persistence.repositories.video_file_repository import (
            SQLModelVideoFileRepository,
        )

        engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)

        with Session(engine) as session:
            repo = SQLModelVideoFileRepository(session)
            result = repo.update_symlink_path(
                Path("/video/inexistant.mkv"),
                Path("/video/nouveau.mkv"),
            )
            assert result is False
