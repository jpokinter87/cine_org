"""Orchestration de la synchronisation CineOrg -> Jellyfin."""

from pathlib import Path

from sqlmodel import Session, select

from src.infrastructure.persistence.models import (
    MovieModel,
    MoviePartModel,
)
from src.services.jellyfin.dataclasses import JellyfinSyncReport
from src.services.jellyfin.nfo_builder import build_movie_nfo
from src.services.jellyfin.tree_builder import (
    ensure_symlink,
    folder_name,
    resolve_source,
)


class JellyfinSyncService:
    """Génère l'arbre Jellyfin dédié (symlinks + NFO) depuis la base."""

    def __init__(self, session: Session, jellyfin_dir: Path) -> None:
        self._session = session
        self._root = Path(jellyfin_dir)
        self._expected_dirs: set[Path] = set()

    def sync(
        self,
        *,
        movies_only: bool = False,
        series_only: bool = False,
        dry_run: bool = False,
        prune: bool = False,
    ) -> JellyfinSyncReport:
        report = JellyfinSyncReport()
        self._expected_dirs = set()
        if not series_only:
            self._sync_movies(report, dry_run)
        if not movies_only:
            self._sync_series(report, dry_run)
        if prune and not dry_run:
            self._prune(report, movies_only, series_only)
        return report

    # --- Films -------------------------------------------------------------

    def _sync_movies(self, report: JellyfinSyncReport, dry_run: bool) -> None:
        films_root = self._root / "Films"
        used_dirs: set[str] = set()
        movies = self._session.exec(select(MovieModel)).all()
        for movie in movies:
            try:
                self._sync_one_movie(movie, films_root, used_dirs, report, dry_run)
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"{movie.title}: {exc}")

    def _sync_one_movie(
        self,
        movie: MovieModel,
        films_root: Path,
        used_dirs: set[str],
        report: JellyfinSyncReport,
        dry_run: bool,
    ) -> None:
        parts = self._session.exec(
            select(MoviePartModel).where(MoviePartModel.movie_id == movie.id)
        ).all()
        sources = self._movie_sources(movie, parts)
        if not sources:
            report.skipped.append(movie.symlink_path or movie.file_path or movie.title)
            return
        if movie.tmdb_id is None:
            report.id_less.append(movie.title)

        name = folder_name(movie.title, movie.year)
        if name in used_dirs:
            name = folder_name(movie.title, movie.year, movie.tmdb_id, with_id=True)
        used_dirs.add(name)
        movie_dir = films_root / name

        if not dry_run:
            base = folder_name(movie.title, movie.year)
            for index, src in enumerate(sources):
                if len(sources) == 1:
                    link_name = f"{base}{src.suffix}"
                else:
                    link_name = f"{base} - cd{index + 1}{src.suffix}"
                ensure_symlink(src, movie_dir / link_name)
            (movie_dir / "movie.nfo").write_text(
                build_movie_nfo(movie), encoding="utf-8"
            )
        self._expected_dirs.add(movie_dir)
        report.movies += 1

    def _movie_sources(
        self, movie: MovieModel, parts: list[MoviePartModel]
    ) -> list[Path]:
        """Liste ordonnée des fichiers physiques à lier (gère le multi-parties)."""
        if parts:
            resolved = []
            for part in sorted(parts, key=lambda p: p.part_number):
                src = resolve_source(part.symlink_path, part.file_path)
                if src:
                    resolved.append(src)
            return resolved
        src = resolve_source(movie.symlink_path, movie.file_path)
        return [src] if src else []

    # --- Séries (étape B) --------------------------------------------------

    def _sync_series(self, report: JellyfinSyncReport, dry_run: bool) -> None:
        # Implémenté à l'étape B.
        pass

    def _prune(
        self, report: JellyfinSyncReport, movies_only: bool, series_only: bool
    ) -> None:
        # Implémenté à l'étape B.
        pass
