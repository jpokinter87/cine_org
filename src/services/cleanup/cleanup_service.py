"""
Service de nettoyage et reorganisation du repertoire video.

CleanupService orchestre la detection et correction de tous les
problemes dans le repertoire video/ en delegant aux modules
analyzers et executors.
"""

from pathlib import Path
from typing import Any

from .analyzers import (
    is_in_managed_scope,
    iter_managed_paths,
    scan_broken_symlinks,
    scan_duplicate_symlinks,
    scan_empty_dirs,
    scan_misplaced_symlinks,
    scan_oversized_dirs,
)
from .dataclasses import (
    BrokenSymlinkInfo,
    CleanupReport,
    CleanupResult,
    DuplicateSymlink,
    MisplacedSymlink,
    SubdivisionPlan,
)
from .executors import (
    clean_empty_dirs,
    delete_broken_symlinks,
    fix_duplicate_symlinks,
    fix_misplaced_symlinks,
    repair_broken_symlinks,
    subdivide_oversized_dirs,
)


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

    def analyze(self, video_dir: Path, max_per_dir: int = 50) -> CleanupReport:
        """
        Analyse le repertoire video et retourne un rapport complet.

        Args:
            video_dir: Repertoire video a analyser.
            max_per_dir: Nombre max de sous-repertoires par repertoire avant subdivision.

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

        duplicates = self._scan_duplicate_symlinks(video_dir)
        oversized = self._scan_oversized_dirs(video_dir, max_per_dir)
        empty = self._scan_empty_dirs(video_dir)

        return CleanupReport(
            video_dir=video_dir,
            broken_symlinks=broken,
            misplaced_symlinks=misplaced,
            duplicate_symlinks=duplicates,
            oversized_dirs=oversized,
            empty_dirs=empty,
            not_in_db_count=not_in_db,
        )

    # --- Delegation des utilitaires de scope (compatibilite) ---

    def _iter_managed_paths(self, video_dir: Path):
        return iter_managed_paths(video_dir)

    def _is_in_managed_scope(self, path: Path, video_dir: Path) -> bool:
        return is_in_managed_scope(path, video_dir)

    # --- Delegation des methodes internes (compatibilite) ---

    def _find_expected_dir(self, video_file, video_dir: Path):
        from .analyzers import _find_expected_dir
        return _find_expected_dir(
            video_file, video_dir,
            self._movie_repo, self._series_repo,
            self._episode_repo, self._organizer_service,
        )

    # --- Delegation des methodes d'analyse (compatibilite) ---

    def _scan_broken_symlinks(self, video_dir: Path):
        return scan_broken_symlinks(video_dir, self._repair_service)

    def _scan_misplaced_symlinks(self, video_dir: Path):
        return scan_misplaced_symlinks(
            video_dir,
            self._video_file_repo,
            self._movie_repo,
            self._series_repo,
            self._episode_repo,
            self._organizer_service,
        )

    def _scan_duplicate_symlinks(self, video_dir: Path):
        return scan_duplicate_symlinks(video_dir)

    def _scan_oversized_dirs(self, video_dir: Path, max_per_dir: int = 50):
        return scan_oversized_dirs(video_dir, max_per_dir)

    def _is_under_series(self, path: Path, video_dir: Path) -> bool:
        from .analyzers import _is_under_series
        return _is_under_series(path, video_dir)

    def _scan_empty_dirs(self, video_dir: Path):
        return scan_empty_dirs(video_dir)

    # --- Delegation des methodes d'execution (compatibilite) ---

    def repair_broken_symlinks(
        self, broken: list[BrokenSymlinkInfo], min_score: float = 90.0
    ) -> CleanupResult:
        return repair_broken_symlinks(broken, self._repair_service, min_score)

    def delete_broken_symlinks(
        self, broken: list[BrokenSymlinkInfo]
    ) -> CleanupResult:
        return delete_broken_symlinks(broken)

    def fix_misplaced_symlinks(
        self, misplaced: list[MisplacedSymlink]
    ) -> CleanupResult:
        return fix_misplaced_symlinks(misplaced, self._video_file_repo)

    def fix_duplicate_symlinks(
        self, duplicates: list[DuplicateSymlink]
    ) -> CleanupResult:
        return fix_duplicate_symlinks(duplicates)

    def subdivide_oversized_dirs(
        self, plans: list[SubdivisionPlan]
    ) -> CleanupResult:
        return subdivide_oversized_dirs(plans, self._video_file_repo)

    def clean_empty_dirs(self, empty_dirs: list[Path]) -> CleanupResult:
        return clean_empty_dirs(empty_dirs)

    # --- Delegation de l'algorithme de subdivision (compatibilite) ---

    def _calculate_subdivision_ranges(
        self, parent_dir: Path, max_per_subdir: int
    ) -> SubdivisionPlan:
        from .subdivision_algorithm import calculate_subdivision_ranges
        return calculate_subdivision_ranges(parent_dir, max_per_subdir)
