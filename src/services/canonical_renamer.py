"""
Service de renommage des fichiers vers le nom canonique issu de la DB.

Pour chaque film, génère le nom canonique via RenamerService, renomme le
fichier physique dans storage/, recrée le symlink dans video/ et met à
jour MovieModel.file_path / symlink_path.

Le hardlink de seeding dans downloads/ est préservé : os.rename() sur
storage/ conserve l'inode, donc le hardlink reste valide.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from loguru import logger
from sqlmodel import Session

from src.core.entities.media import Movie
from src.core.ports.parser import IMediaInfoExtractor
from src.infrastructure.persistence.models import MovieModel
from src.services.renamer import generate_movie_filename


@dataclass
class RenameOutcome:
    """Résultat d'une tentative de renommage."""

    movie_id: int
    status: str  # "renamed" | "already_canonical" | "file_missing" | "conflict" | "no_file_path" | "error"
    old_name: Optional[str] = None
    new_name: Optional[str] = None
    old_storage: Optional[Path] = None
    new_storage: Optional[Path] = None
    old_symlink: Optional[Path] = None
    new_symlink: Optional[Path] = None
    reason: Optional[str] = None


def _to_entity(model: MovieModel) -> Movie:
    """Construit un Movie entity depuis un MovieModel pour le renamer."""
    return Movie(
        id=str(model.id) if model.id is not None else None,
        tmdb_id=model.tmdb_id,
        title=model.title,
        original_title=model.original_title,
        year=model.year,
        duration_seconds=model.duration_seconds,
    )


class CanonicalRenamerService:
    """Renomme les fichiers films selon le titre canonique de la DB."""

    def __init__(
        self,
        session: Session,
        media_info_extractor: IMediaInfoExtractor,
    ) -> None:
        self._session = session
        self._extractor = media_info_extractor

    def rename_movie(self, movie_id: int, dry_run: bool = True) -> RenameOutcome:
        """Renomme un film vers son nom canonique DB. Dry-run par défaut."""
        movie = self._session.get(MovieModel, movie_id)
        if movie is None:
            return RenameOutcome(
                movie_id=movie_id, status="error", reason="movie_not_found"
            )

        if not movie.file_path:
            return RenameOutcome(
                movie_id=movie_id, status="no_file_path"
            )

        storage_path = Path(movie.file_path)
        if not storage_path.exists():
            return RenameOutcome(
                movie_id=movie_id,
                status="file_missing",
                old_storage=storage_path,
                reason=str(storage_path),
            )

        # Extraire les métadonnées techniques (fallback silencieux si échec)
        media_info = None
        try:
            media_info = self._extractor.extract(storage_path)
        except Exception as e:
            logger.debug(f"MediaInfo échoue pour {storage_path} : {e}")

        entity = _to_entity(movie)
        new_name = generate_movie_filename(
            entity, media_info, storage_path.suffix
        )

        if new_name == storage_path.name:
            return RenameOutcome(
                movie_id=movie_id,
                status="already_canonical",
                old_name=storage_path.name,
                new_name=new_name,
            )

        new_storage = storage_path.with_name(new_name)

        symlink_path = Path(movie.symlink_path) if movie.symlink_path else None
        new_symlink = symlink_path.with_name(new_name) if symlink_path else None

        # Conflit : la cible existe déjà (fichier différent ou symlink orphelin)
        if new_storage.exists() and new_storage.resolve() != storage_path.resolve():
            return RenameOutcome(
                movie_id=movie_id,
                status="conflict",
                old_name=storage_path.name,
                new_name=new_name,
                old_storage=storage_path,
                new_storage=new_storage,
                reason="storage_target_exists",
            )
        if new_symlink is not None and new_symlink != symlink_path:
            if new_symlink.is_symlink() or new_symlink.exists():
                return RenameOutcome(
                    movie_id=movie_id,
                    status="conflict",
                    old_name=storage_path.name,
                    new_name=new_name,
                    old_storage=storage_path,
                    new_storage=new_storage,
                    old_symlink=symlink_path,
                    new_symlink=new_symlink,
                    reason="symlink_target_exists",
                )

        if dry_run:
            return RenameOutcome(
                movie_id=movie_id,
                status="renamed",
                old_name=storage_path.name,
                new_name=new_name,
                old_storage=storage_path,
                new_storage=new_storage,
                old_symlink=symlink_path,
                new_symlink=new_symlink,
            )

        # Exécution réelle
        try:
            storage_path.rename(new_storage)
            if symlink_path is not None and new_symlink is not None:
                if symlink_path.is_symlink() or symlink_path.exists():
                    symlink_path.unlink()
                new_symlink.symlink_to(new_storage)
            movie.file_path = str(new_storage)
            if new_symlink is not None:
                movie.symlink_path = str(new_symlink)
            self._session.add(movie)
            self._session.commit()
        except Exception as e:
            logger.error(f"Renommage échoué pour movie {movie_id} : {e}")
            return RenameOutcome(
                movie_id=movie_id,
                status="error",
                old_storage=storage_path,
                new_storage=new_storage,
                reason=str(e),
            )

        return RenameOutcome(
            movie_id=movie_id,
            status="renamed",
            old_name=storage_path.name,
            new_name=new_name,
            old_storage=storage_path,
            new_storage=new_storage,
            old_symlink=symlink_path,
            new_symlink=new_symlink,
        )

    def rename_movies(
        self,
        movie_ids: list[int],
        dry_run: bool = True,
    ) -> list[RenameOutcome]:
        """Renomme une série de films. Skip les échecs individuels."""
        return [self.rename_movie(mid, dry_run=dry_run) for mid in movie_ids]
