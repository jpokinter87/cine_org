"""Émet un seul titre (film ou série intégrale) dans l'arbre Partage éphémère.

Réutilise les briques pures de src/services/jellyfin/ et interroge les models via
une Session SQLModel (même approche que JellyfinSyncService).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from sqlmodel import Session, select

from src.infrastructure.persistence.models import (
    EpisodeModel,
    MovieModel,
    MoviePartModel,
    SeriesModel,
)
from src.services.jellyfin.nfo_builder import (
    build_episode_nfo,
    build_movie_nfo,
    build_tvshow_nfo,
)
from src.services.jellyfin.tree_builder import (
    ensure_symlink,
    episode_filename,
    folder_name,
    resolve_source,
)
from src.services.share.exceptions import ShareError


class JellyfinShareBuilder:
    """Construit/détruit l'arbre Partage éphémère pour un titre donné."""

    def __init__(self, session: Session, partage_dir: Path | str) -> None:
        self._session = session
        self._root = Path(partage_dir)

    def clear(self) -> None:
        """Vide entièrement le dossier Partage (Films + Series)."""
        for sub in ("Films", "Series"):
            d = self._root / sub
            if d.exists():
                shutil.rmtree(d)

    def populate_movie(self, movie_id: int) -> str:
        """Émet un film dans Partage/Films/<dossier>.

        Gère les films simples (fichier unique) et les films multi-parties
        (table MoviePartModel). Lève ShareError si aucune source n'est résolvable.

        Retourne le nom du dossier créé (ex. « Inception (2010) »).
        """
        movie = self._session.get(MovieModel, movie_id)
        if movie is None:
            raise ShareError(f"Film introuvable en base : {movie_id}")
        parts = self._session.exec(
            select(MoviePartModel)
            .where(MoviePartModel.movie_id == movie.id)
            .order_by(MoviePartModel.part_number)
        ).all()
        sources = self._movie_sources(movie, list(parts))
        if not sources:
            raise ShareError(f"Aucun fichier source résolvable pour : {movie.title}")

        name = folder_name(movie.title, movie.year)
        movie_dir = self._root / "Films" / name
        for index, src in enumerate(sources):
            if len(sources) == 1:
                link_name = f"{name}{src.suffix}"
            else:
                link_name = f"{name} - cd{index + 1}{src.suffix}"
            ensure_symlink(src, movie_dir / link_name)
        # movie_dir est créé par ensure_symlink (via parent.mkdir)
        (movie_dir / "movie.nfo").write_text(build_movie_nfo(movie), encoding="utf-8")
        return name

    def populate_series(self, series_id: int) -> str:
        """Émet une série intégrale dans Partage/Series/<dossier>.

        Crée un dossier par saison (Saison XX) contenant les symlinks et NFO
        d'épisodes. Lève ShareError si aucun épisode n'est résolvable.

        Retourne le nom du dossier créé (ex. « Gomorra (2014) »).
        """
        series = self._session.get(SeriesModel, series_id)
        if series is None:
            raise ShareError(f"Série introuvable en base : {series_id}")
        episodes = self._session.exec(
            select(EpisodeModel)
            .where(EpisodeModel.series_id == series.id)
            .order_by(EpisodeModel.season_number, EpisodeModel.episode_number)
        ).all()
        available: list[tuple[EpisodeModel, Path]] = []
        for ep in episodes:
            src = resolve_source(ep.symlink_path, ep.file_path)
            if src is not None:
                available.append((ep, src))
        if not available:
            raise ShareError(f"Aucun épisode résolvable pour : {series.title}")

        name = folder_name(series.title, series.year)
        show_dir = self._root / "Series" / name
        show_dir.mkdir(parents=True, exist_ok=True)
        (show_dir / "tvshow.nfo").write_text(build_tvshow_nfo(series), encoding="utf-8")
        for ep, src in available:
            season_dir = show_dir / f"Saison {ep.season_number:02d}"
            link_name = episode_filename(
                series.title,
                series.year,
                ep.season_number,
                ep.episode_number,
                src.suffix,
            )
            ensure_symlink(src, season_dir / link_name)
            (season_dir / f"{Path(link_name).stem}.nfo").write_text(
                build_episode_nfo(ep), encoding="utf-8"
            )
        return name

    def _movie_sources(
        self, movie: MovieModel, parts: list[MoviePartModel]
    ) -> list[Path]:
        """Résout les fichiers physiques d'un film (simple ou multi-parties)."""
        if parts:
            out: list[Path] = []
            for part in parts:
                s = resolve_source(part.symlink_path, part.file_path)
                if s is not None:
                    out.append(s)
            return out
        s = resolve_source(movie.symlink_path, movie.file_path)
        return [s] if s is not None else []
