"""Orchestration de la synchronisation CineOrg -> Jellyfin."""

import shutil
from pathlib import Path

from sqlmodel import Session, select

from src.infrastructure.persistence.models import (
    EpisodeModel,
    MovieModel,
    MoviePartModel,
    SeriesModel,
)
from src.services.jellyfin.dataclasses import JellyfinSyncReport
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
    unique_folder_name,
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

        name = unique_folder_name(movie.title, movie.year, movie.tmdb_id, used_dirs)
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
        series_root = self._root / "Séries"
        used_dirs: set[str] = set()
        all_series = self._session.exec(select(SeriesModel)).all()
        for series in all_series:
            try:
                self._sync_one_series(series, series_root, used_dirs, report, dry_run)
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"{series.title}: {exc}")

    def _sync_one_series(
        self,
        series: SeriesModel,
        series_root: Path,
        used_dirs: set[str],
        report: JellyfinSyncReport,
        dry_run: bool,
    ) -> None:
        episodes = self._session.exec(
            select(EpisodeModel).where(EpisodeModel.series_id == series.id)
        ).all()
        resolved = [
            (ep, resolve_source(ep.symlink_path, ep.file_path)) for ep in episodes
        ]
        for ep, src in resolved:
            if src is None:
                report.skipped.append(ep.symlink_path or ep.file_path or ep.title)
        available = [(ep, src) for ep, src in resolved if src is not None]
        if not available:
            return  # série sans aucun épisode présent : on ne crée rien

        if series.tvdb_id is None and series.tmdb_id is None:
            report.id_less.append(series.title)

        name = unique_folder_name(series.title, series.year, series.tmdb_id, used_dirs)
        used_dirs.add(name)
        show_dir = series_root / name

        if not dry_run:
            show_dir.mkdir(parents=True, exist_ok=True)
            (show_dir / "tvshow.nfo").write_text(
                build_tvshow_nfo(series), encoding="utf-8"
            )
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
        self._expected_dirs.add(show_dir)
        report.series += 1
        report.episodes += len(available)

    def _prune(
        self, report: JellyfinSyncReport, movies_only: bool, series_only: bool
    ) -> None:
        """Supprime les dossiers de l'arbre Jellyfin absents de la base."""
        roots = []
        if not series_only:
            roots.append(self._root / "Films")
        if not movies_only:
            roots.append(self._root / "Séries")
        for root in roots:
            if not root.exists():
                continue
            for entry in root.iterdir():
                if entry.is_dir() and entry not in self._expected_dirs:
                    shutil.rmtree(entry)
                    report.pruned.append(str(entry))
