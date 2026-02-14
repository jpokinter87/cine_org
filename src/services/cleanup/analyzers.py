"""
Methodes d'analyse (scan) pour la detection de problemes.

Regroupe les methodes _scan_* extraites de CleanupService
pour la detection de symlinks casses, mal places, dupliques,
repertoires surcharges et vides.
"""

from collections import defaultdict
from pathlib import Path
from typing import Any, Iterator, Optional

from loguru import logger
from sqlmodel import select

from src.core.entities.media import Movie, Series
from src.core.entities.video import VideoFile
from src.infrastructure.persistence.models import MovieModel, EpisodeModel, SeriesModel

from .dataclasses import (
    MANAGED_SUBDIRS,
    BrokenSymlinkInfo,
    DuplicateSymlink,
    MisplacedSymlink,
    SubdivisionPlan,
)
from .subdivision_algorithm import _refine_plans_destinations, calculate_subdivision_ranges


def iter_managed_paths(video_dir: Path) -> Iterator[Path]:
    """Itere recursivement sur les fichiers/dossiers dans Films/ et Series/ uniquement."""
    for subdir_name in MANAGED_SUBDIRS:
        subdir = video_dir / subdir_name
        if subdir.exists():
            yield from subdir.rglob("*")


def is_in_managed_scope(path: Path, video_dir: Path) -> bool:
    """Verifie si un chemin est sous l'un des sous-repertoires geres."""
    try:
        relative = path.relative_to(video_dir)
    except ValueError:
        return False
    parts = relative.parts
    return len(parts) > 0 and parts[0] in MANAGED_SUBDIRS


def scan_broken_symlinks(
    video_dir: Path,
    repair_service: Any,
) -> list[BrokenSymlinkInfo]:
    """
    Detecte les symlinks casses via RepairService.

    Args:
        video_dir: Repertoire video a scanner.
        repair_service: Service de reparation des symlinks.

    Returns:
        Liste de BrokenSymlinkInfo avec le meilleur candidat pour chaque lien.
    """
    broken_links = repair_service.find_broken_symlinks()
    result = []

    for link in broken_links:
        # Filtrer les liens hors du scope gere (Films/, Series/)
        if not is_in_managed_scope(link, video_dir):
            continue
        # Lire la cible originale
        try:
            original_target = link.readlink()
        except OSError:
            original_target = Path("")

        # Chercher les candidats
        targets = repair_service.find_possible_targets(link)

        best_candidate = None
        best_score = 0.0
        if targets:
            best_candidate = targets[0][0]
            best_score = targets[0][1]

        result.append(
            BrokenSymlinkInfo(
                symlink_path=link,
                original_target=original_target,
                best_candidate=best_candidate,
                candidate_score=best_score,
            )
        )

    return result


def scan_misplaced_symlinks(
    video_dir: Path,
    video_file_repo: Any,
    movie_repo: Any,
    series_repo: Any,
    episode_repo: Any,
    organizer_service: Any,
) -> tuple[list[MisplacedSymlink], int]:
    """
    Detecte les symlinks valides places dans le mauvais repertoire.

    Pour chaque symlink valide, verifie que son emplacement correspond
    au chemin attendu calcule par OrganizerService.

    Args:
        video_dir: Repertoire video a scanner.
        video_file_repo: Repository des fichiers video.
        movie_repo: Repository des films.
        series_repo: Repository des series.
        episode_repo: Repository des episodes.
        organizer_service: Service d'organisation.

    Returns:
        Tuple (liste de MisplacedSymlink, nombre de symlinks non en BDD).
    """
    misplaced = []
    not_in_db = 0

    for symlink in iter_managed_paths(video_dir):
        if not symlink.is_symlink():
            continue

        # Ignorer les symlinks casses
        try:
            target = symlink.resolve()
            if not target.exists():
                continue
        except OSError:
            continue

        # Chercher en BDD
        video_file = video_file_repo.get_by_symlink_path(symlink)
        if video_file is None:
            video_file = video_file_repo.get_by_path(target)

        if video_file is None:
            not_in_db += 1
            continue

        # Determiner le type : film ou episode
        expected_dir = _find_expected_dir(
            video_file, video_dir,
            movie_repo, series_repo, episode_repo, organizer_service,
        )
        if expected_dir is None:
            continue

        # Comparer le repertoire actuel avec le repertoire attendu
        current_dir = symlink.parent
        if current_dir != expected_dir:
            misplaced.append(
                MisplacedSymlink(
                    symlink_path=symlink,
                    target_path=target,
                    current_dir=current_dir,
                    expected_dir=expected_dir,
                )
            )

    return misplaced, not_in_db


def _find_expected_dir(
    video_file: VideoFile,
    video_dir: Path,
    movie_repo: Any,
    series_repo: Any,
    episode_repo: Any,
    organizer_service: Any,
) -> Optional[Path]:
    """
    Calcule le repertoire attendu pour un fichier video.

    Cherche le Movie ou Episode associe et calcule le chemin via OrganizerService.
    """
    import json

    file_path_str = str(video_file.path) if video_file.path else None
    if not file_path_str:
        return None

    # Chercher un film par file_path
    try:
        movie_model = movie_repo._session.exec(
            select(MovieModel).where(MovieModel.file_path == file_path_str)
        ).first()

        if movie_model:
            genres_list = json.loads(movie_model.genres_json) if movie_model.genres_json else []
            movie = Movie(
                id=str(movie_model.id) if movie_model.id else None,
                tmdb_id=movie_model.tmdb_id,
                title=movie_model.title,
                original_title=movie_model.original_title,
                year=movie_model.year,
                genres=tuple(genres_list),
            )
            return organizer_service.get_movie_video_destination(movie, video_dir)
    except Exception:
        logger.debug(f"Erreur lors de la recherche du film pour {file_path_str}")

    # Chercher un episode par file_path
    try:
        episode_model = episode_repo._session.exec(
            select(EpisodeModel).where(EpisodeModel.file_path == file_path_str)
        ).first()

        if episode_model:
            series_model = series_repo._session.exec(
                select(SeriesModel).where(SeriesModel.id == episode_model.series_id)
            ).first()

            if series_model:
                genres_list = json.loads(series_model.genres_json) if series_model.genres_json else []
                series = Series(
                    id=str(series_model.id) if series_model.id else None,
                    tvdb_id=series_model.tvdb_id,
                    title=series_model.title,
                    original_title=series_model.original_title,
                    year=series_model.year,
                    genres=tuple(genres_list),
                )
                return organizer_service.get_series_video_destination(
                    series, episode_model.season_number, video_dir,
                )
    except Exception:
        logger.debug(f"Erreur lors de la recherche de l'episode pour {file_path_str}")

    return None


def scan_duplicate_symlinks(video_dir: Path) -> list[DuplicateSymlink]:
    """
    Detecte les symlinks dupliques dans le meme repertoire.

    Deux symlinks sont dupliques s'ils sont dans le meme repertoire
    et pointent vers le meme fichier physique (apres resolution).
    Le symlink a conserver est celui avec le nom le plus long.

    Args:
        video_dir: Repertoire video a scanner.

    Returns:
        Liste de DuplicateSymlink pour chaque groupe de doublons.
    """
    # Grouper les symlinks valides par (repertoire, cible resolue)
    groups: dict[tuple[Path, Path], list[Path]] = defaultdict(list)

    for path in iter_managed_paths(video_dir):
        if not path.is_symlink():
            continue
        try:
            resolved = path.resolve()
            if not resolved.exists():
                continue
        except OSError:
            continue
        groups[(path.parent, resolved)].append(path)

    # Pour chaque groupe >= 2, determiner keep/remove
    result = []
    for (directory, target), symlinks in groups.items():
        if len(symlinks) < 2:
            continue
        # Conserver le nom le plus long (plus de metadonnees)
        symlinks.sort(key=lambda p: len(p.name), reverse=True)
        keep = symlinks[0]
        remove = symlinks[1:]
        result.append(
            DuplicateSymlink(
                directory=directory,
                target_path=target,
                keep=keep,
                remove=remove,
            )
        )

    return result


def scan_oversized_dirs(
    video_dir: Path, max_per_dir: int = 50
) -> list[SubdivisionPlan]:
    """
    Detecte les repertoires avec trop d'elements directs (symlinks + repertoires).

    Exception : les repertoires sous Series/ ne contenant que des symlinks
    (= episodes d'une serie) sont ignores, meme au-dela du seuil.

    Args:
        video_dir: Repertoire video a scanner.
        max_per_dir: Seuil d'elements avant subdivision.

    Returns:
        Liste de SubdivisionPlan pour chaque repertoire surcharge.
    """
    plans = []

    for dirpath in iter_managed_paths(video_dir):
        if not dirpath.is_dir():
            continue

        # Compter tous les elements directs (symlinks et repertoires)
        items = [
            item for item in dirpath.iterdir()
            if item.is_symlink() or item.is_dir()
        ]

        if not items:
            continue

        # Ignorer les repertoires d'episodes sous Series/
        has_only_symlinks = all(item.is_symlink() for item in items)
        if has_only_symlinks and _is_under_series(dirpath, video_dir):
            continue

        if len(items) > max_per_dir:
            plan = calculate_subdivision_ranges(dirpath, max_per_dir)
            plans.append(plan)

    _refine_plans_destinations(plans)
    return plans


def _is_under_series(path: Path, video_dir: Path) -> bool:
    """Verifie si un chemin est sous le sous-repertoire Series/."""
    try:
        relative = path.relative_to(video_dir)
    except ValueError:
        return False
    parts = relative.parts
    return len(parts) > 0 and parts[0] == "Séries"


def scan_empty_dirs(video_dir: Path) -> list[Path]:
    """
    Detecte les repertoires vides (bottom-up).

    Un repertoire est vide s'il ne contient ni fichiers ni
    sous-repertoires non-vides. Exclut la racine video_dir.

    Args:
        video_dir: Repertoire video a scanner.

    Returns:
        Liste des repertoires vides.
    """
    empty = []

    # Parcours bottom-up : trier par profondeur decroissante
    all_dirs = sorted(
        [d for d in iter_managed_paths(video_dir) if d.is_dir()],
        key=lambda p: len(p.parts),
        reverse=True,
    )

    for dirpath in all_dirs:
        # Exclure la racine
        if dirpath == video_dir:
            continue

        # Verifier si le repertoire est vide
        try:
            contents = list(dirpath.iterdir())
            if not contents:
                empty.append(dirpath)
        except PermissionError:
            continue

    return empty
