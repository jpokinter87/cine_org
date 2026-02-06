"""
Service de nettoyage et reorganisation du repertoire video.

Detecte et corrige les problemes dans le repertoire video/ :
- Symlinks casses
- Symlinks mal places (mauvais genre/subdivision)
- Repertoires surcharges (>50 fichiers) non subdivises
- Repertoires vides residuels

Scope : symlinks video/ uniquement (pas les fichiers physiques dans storage/).
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from loguru import logger
from sqlmodel import select

from src.core.entities.media import Movie, Series
from src.core.entities.video import VideoFile
from src.infrastructure.persistence.models import MovieModel, EpisodeModel, SeriesModel
from src.services.organizer import _strip_article


class CleanupStepType(str, Enum):
    """Types de problemes detectes lors du cleanup."""

    BROKEN_SYMLINK = "broken_symlink"
    MISPLACED_SYMLINK = "misplaced_symlink"
    OVERSIZED_DIR = "oversized_dir"
    EMPTY_DIR = "empty_dir"


@dataclass
class BrokenSymlinkInfo:
    """Informations sur un symlink casse avec le meilleur candidat de reparation."""

    symlink_path: Path
    original_target: Path
    best_candidate: Optional[Path] = None
    candidate_score: float = 0.0


@dataclass
class MisplacedSymlink:
    """Symlink valide mais place dans le mauvais repertoire."""

    symlink_path: Path
    target_path: Path
    current_dir: Path
    expected_dir: Path
    media_title: str = ""


@dataclass
class SubdivisionPlan:
    """Plan de subdivision d'un repertoire surcharge."""

    parent_dir: Path
    current_count: int
    max_allowed: int
    ranges: list[tuple[str, str]]
    items_to_move: list[tuple[Path, Path]]


@dataclass
class CleanupReport:
    """Rapport complet d'analyse du repertoire video."""

    video_dir: Path
    broken_symlinks: list[BrokenSymlinkInfo]
    misplaced_symlinks: list[MisplacedSymlink]
    oversized_dirs: list[SubdivisionPlan]
    empty_dirs: list[Path]
    not_in_db_count: int = 0

    @property
    def has_issues(self) -> bool:
        """Retourne True s'il y a au moins un probleme detecte."""
        return self.total_issues > 0

    @property
    def total_issues(self) -> int:
        """Retourne le nombre total de problemes."""
        return (
            len(self.broken_symlinks)
            + len(self.misplaced_symlinks)
            + len(self.oversized_dirs)
            + len(self.empty_dirs)
        )


@dataclass
class CleanupResult:
    """Resultat de l'execution des corrections."""

    repaired_symlinks: int = 0
    failed_repairs: int = 0
    moved_symlinks: int = 0
    subdivisions_created: int = 0
    symlinks_redistributed: int = 0
    empty_dirs_removed: int = 0
    errors: list[str] = field(default_factory=list)


class CleanupService:
    """
    Service de nettoyage et reorganisation du repertoire video.

    Orchestre la detection et correction de tous les problemes
    dans le repertoire video/ en reutilisant les services existants.
    """

    def __init__(
        self,
        repair_service: Any,
        organizer_service: Any,
        video_file_repo: Any,
        movie_repo: Any,
        series_repo: Any,
        episode_repo: Any,
    ) -> None:
        """
        Initialise le service de cleanup.

        Args:
            repair_service: Service de reparation des symlinks (RepairService)
            organizer_service: Service d'organisation (OrganizerService)
            video_file_repo: Repository des fichiers video
            movie_repo: Repository des films
            series_repo: Repository des series
            episode_repo: Repository des episodes
        """
        self._repair_service = repair_service
        self._organizer_service = organizer_service
        self._video_file_repo = video_file_repo
        self._movie_repo = movie_repo
        self._series_repo = series_repo
        self._episode_repo = episode_repo

    def analyze(self, video_dir: Path, max_files: int = 50) -> CleanupReport:
        """
        Analyse le repertoire video et retourne un rapport complet.

        Args:
            video_dir: Repertoire video a analyser.
            max_files: Nombre max de fichiers par repertoire avant subdivision.

        Returns:
            CleanupReport avec tous les problemes detectes.
        """
        broken = self._scan_broken_symlinks(video_dir)
        misplaced_result = self._scan_misplaced_symlinks(video_dir)

        # _scan_misplaced_symlinks retourne (list, int) ou list selon le contexte
        if isinstance(misplaced_result, tuple):
            misplaced, not_in_db = misplaced_result
        else:
            misplaced = misplaced_result
            not_in_db = 0

        oversized = self._scan_oversized_dirs(video_dir, max_files)
        empty = self._scan_empty_dirs(video_dir)

        return CleanupReport(
            video_dir=video_dir,
            broken_symlinks=broken,
            misplaced_symlinks=misplaced,
            oversized_dirs=oversized,
            empty_dirs=empty,
            not_in_db_count=not_in_db,
        )

    # ------------------------------------------------------------------
    # Analyse
    # ------------------------------------------------------------------

    def _scan_broken_symlinks(self, video_dir: Path) -> list[BrokenSymlinkInfo]:
        """
        Detecte les symlinks casses via RepairService.

        Args:
            video_dir: Repertoire video a scanner.

        Returns:
            Liste de BrokenSymlinkInfo avec le meilleur candidat pour chaque lien.
        """
        broken_links = self._repair_service.find_broken_symlinks()
        result = []

        for link in broken_links:
            # Lire la cible originale
            try:
                original_target = link.readlink()
            except OSError:
                original_target = Path("")

            # Chercher les candidats
            targets = self._repair_service.find_possible_targets(link)

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

    def _scan_misplaced_symlinks(
        self, video_dir: Path
    ) -> tuple[list[MisplacedSymlink], int]:
        """
        Detecte les symlinks valides places dans le mauvais repertoire.

        Pour chaque symlink valide, verifie que son emplacement correspond
        au chemin attendu calcule par OrganizerService.

        Args:
            video_dir: Repertoire video a scanner.

        Returns:
            Tuple (liste de MisplacedSymlink, nombre de symlinks non en BDD).
        """
        misplaced = []
        not_in_db = 0

        for symlink in video_dir.rglob("*"):
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
            video_file = self._video_file_repo.get_by_symlink_path(symlink)
            if video_file is None:
                video_file = self._video_file_repo.get_by_path(target)

            if video_file is None:
                not_in_db += 1
                continue

            # Determiner le type : film ou episode
            expected_dir = self._find_expected_dir(video_file, video_dir)
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
        self, video_file: VideoFile, video_dir: Path
    ) -> Optional[Path]:
        """
        Calcule le repertoire attendu pour un fichier video.

        Cherche le Movie ou Episode associe et calcule le chemin via OrganizerService.

        Args:
            video_file: Le fichier video.
            video_dir: Repertoire video racine.

        Returns:
            Chemin du repertoire attendu, ou None si non determinable.
        """
        file_path_str = str(video_file.path) if video_file.path else None
        if not file_path_str:
            return None

        # Chercher un film par file_path
        try:
            movie_model = self._movie_repo._session.exec(
                select(MovieModel).where(MovieModel.file_path == file_path_str)
            ).first()

            if movie_model:
                import json
                genres_list = json.loads(movie_model.genres_json) if movie_model.genres_json else []
                movie = Movie(
                    id=str(movie_model.id) if movie_model.id else None,
                    tmdb_id=movie_model.tmdb_id,
                    title=movie_model.title,
                    original_title=movie_model.original_title,
                    year=movie_model.year,
                    genres=tuple(genres_list),
                )
                return self._organizer_service.get_movie_video_destination(movie, video_dir)
        except Exception:
            logger.debug(f"Erreur lors de la recherche du film pour {file_path_str}")

        # Chercher un episode par file_path
        try:
            episode_model = self._episode_repo._session.exec(
                select(EpisodeModel).where(EpisodeModel.file_path == file_path_str)
            ).first()

            if episode_model:
                series_model = self._series_repo._session.exec(
                    select(SeriesModel).where(SeriesModel.id == episode_model.series_id)
                ).first()

                if series_model:
                    import json
                    genres_list = json.loads(series_model.genres_json) if series_model.genres_json else []
                    series = Series(
                        id=str(series_model.id) if series_model.id else None,
                        tvdb_id=series_model.tvdb_id,
                        title=series_model.title,
                        original_title=series_model.original_title,
                        year=series_model.year,
                        genres=tuple(genres_list),
                    )
                    return self._organizer_service.get_series_video_destination(
                        series, episode_model.season_number, video_dir,
                    )
        except Exception:
            logger.debug(f"Erreur lors de la recherche de l'episode pour {file_path_str}")

        return None

    def _scan_oversized_dirs(
        self, video_dir: Path, max_files: int = 50
    ) -> list[SubdivisionPlan]:
        """
        Detecte les repertoires avec trop de fichiers.

        Parcourt recursivement video_dir et identifie les repertoires
        feuilles contenant plus de max_files elements.

        Args:
            video_dir: Repertoire video a scanner.
            max_files: Seuil de fichiers avant subdivision.

        Returns:
            Liste de SubdivisionPlan pour chaque repertoire surcharge.
        """
        plans = []

        for dirpath in video_dir.rglob("*"):
            if not dirpath.is_dir():
                continue

            # Compter les elements directs (symlinks et repertoires)
            items = [
                item for item in dirpath.iterdir()
                if item.is_symlink() or item.is_dir()
            ]

            # Verifier que c'est un repertoire "feuille" :
            # ne contient que des symlinks (pas de sous-repertoires de subdivision)
            has_only_symlinks = all(item.is_symlink() for item in items)
            if not has_only_symlinks or not items:
                continue

            if len(items) > max_files:
                plan = self._calculate_subdivision_ranges(dirpath, max_files)
                plans.append(plan)

        return plans

    def _scan_empty_dirs(self, video_dir: Path) -> list[Path]:
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
            [d for d in video_dir.rglob("*") if d.is_dir()],
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

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def repair_broken_symlinks(
        self, broken: list[BrokenSymlinkInfo], min_score: float = 90.0
    ) -> CleanupResult:
        """
        Repare les symlinks casses ayant un candidat avec score suffisant.

        Args:
            broken: Liste des symlinks casses a reparer.
            min_score: Score minimum pour auto-reparation.

        Returns:
            CleanupResult avec les compteurs de reparation.
        """
        result = CleanupResult()

        for info in broken:
            if info.best_candidate is None or info.candidate_score < min_score:
                continue

            try:
                success = self._repair_service.repair_symlink(
                    info.symlink_path, info.best_candidate
                )
                if success:
                    result.repaired_symlinks += 1
                else:
                    result.failed_repairs += 1
            except Exception as e:
                result.failed_repairs += 1
                result.errors.append(f"Reparation echouee {info.symlink_path}: {e}")

        return result

    def fix_misplaced_symlinks(
        self, misplaced: list[MisplacedSymlink]
    ) -> CleanupResult:
        """
        Deplace les symlinks mal places vers le bon repertoire.

        Args:
            misplaced: Liste des symlinks a deplacer.

        Returns:
            CleanupResult avec le nombre de symlinks deplaces.
        """
        result = CleanupResult()

        for info in misplaced:
            try:
                info.expected_dir.mkdir(parents=True, exist_ok=True)
                new_path = info.expected_dir / info.symlink_path.name
                info.symlink_path.rename(new_path)
                self._video_file_repo.update_symlink_path(info.symlink_path, new_path)
                result.moved_symlinks += 1
            except Exception as e:
                result.errors.append(f"Deplacement echoue {info.symlink_path}: {e}")

        return result

    def subdivide_oversized_dirs(
        self, plans: list[SubdivisionPlan]
    ) -> CleanupResult:
        """
        Subdivise les repertoires surcharges selon les plans fournis.

        Args:
            plans: Liste des plans de subdivision.

        Returns:
            CleanupResult avec les compteurs de subdivision.
        """
        result = CleanupResult()

        for plan in plans:
            try:
                # Creer les sous-repertoires
                dest_dirs = set()
                for _, dest in plan.items_to_move:
                    dest_dirs.add(dest.parent)

                for dest_dir in dest_dirs:
                    dest_dir.mkdir(parents=True, exist_ok=True)

                # Deplacer les symlinks
                for source, dest in plan.items_to_move:
                    try:
                        source.rename(dest)
                        self._video_file_repo.update_symlink_path(source, dest)
                        result.symlinks_redistributed += 1
                    except Exception as e:
                        result.errors.append(f"Deplacement echoue {source}: {e}")

                result.subdivisions_created += 1
            except Exception as e:
                result.errors.append(f"Subdivision echouee {plan.parent_dir}: {e}")

        return result

    def clean_empty_dirs(self, empty_dirs: list[Path]) -> CleanupResult:
        """
        Supprime les repertoires vides.

        Args:
            empty_dirs: Liste des repertoires vides a supprimer.

        Returns:
            CleanupResult avec le nombre de repertoires supprimes.
        """
        result = CleanupResult()

        # Trier par profondeur decroissante pour supprimer les plus profonds d'abord
        sorted_dirs = sorted(empty_dirs, key=lambda p: len(p.parts), reverse=True)

        for dirpath in sorted_dirs:
            try:
                dirpath.rmdir()
                result.empty_dirs_removed += 1
            except OSError as e:
                result.errors.append(f"Suppression echouee {dirpath}: {e}")

        return result

    # ------------------------------------------------------------------
    # Algorithme de subdivision
    # ------------------------------------------------------------------

    def _calculate_subdivision_ranges(
        self, parent_dir: Path, max_per_subdir: int
    ) -> SubdivisionPlan:
        """
        Calcule les plages de subdivision pour un repertoire surcharge.

        Args:
            parent_dir: Repertoire a subdiviser.
            max_per_subdir: Nombre max d'elements par sous-repertoire.

        Returns:
            SubdivisionPlan avec les plages et les mouvements.
        """
        # Lister les elements directs (symlinks ou dossiers)
        items = sorted(parent_dir.iterdir())
        items = [i for i in items if i.is_symlink() or i.is_dir()]

        # Pour chaque item, calculer la cle de tri (2 lettres)
        keyed: list[tuple[str, Path]] = []
        for item in items:
            title = item.name
            stripped = _strip_article(title).strip()
            if len(stripped) >= 2:
                sort_key = stripped.upper()[:2]
            else:
                sort_key = stripped.upper().ljust(2, "A")
            keyed.append((sort_key, item))

        keyed.sort(key=lambda x: x[0])

        # Diviser en groupes de taille max_per_subdir
        ranges: list[tuple[str, str]] = []
        moves: list[tuple[Path, Path]] = []

        for i in range(0, len(keyed), max_per_subdir):
            group = keyed[i: i + max_per_subdir]
            start = group[0][0][0] + group[0][0][1:].lower()
            end = group[-1][0][0] + group[-1][0][1:].lower()
            range_label = f"{start}-{end}"
            dest = parent_dir / range_label

            for _, item in group:
                moves.append((item, dest / item.name))

            ranges.append((start, end))

        return SubdivisionPlan(
            parent_dir=parent_dir,
            current_count=len(keyed),
            max_allowed=max_per_subdir,
            ranges=ranges,
            items_to_move=moves,
        )
