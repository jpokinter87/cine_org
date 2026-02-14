"""
Dataclasses et enums pour le service de cleanup.

Definit les structures de donnees utilisees dans les rapports
d'analyse et resultats d'execution du cleanup.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


MANAGED_SUBDIRS = ("Films", "Séries")


class CleanupStepType(str, Enum):
    """Types de problemes detectes lors du cleanup."""

    BROKEN_SYMLINK = "broken_symlink"
    MISPLACED_SYMLINK = "misplaced_symlink"
    DUPLICATE_SYMLINK = "duplicate_symlink"
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
class DuplicateSymlink:
    """Symlinks dupliques : plusieurs liens dans le meme repertoire pointant vers le meme fichier."""

    directory: Path
    target_path: Path
    keep: Path
    remove: list[Path]


@dataclass
class SubdivisionPlan:
    """Plan de subdivision d'un repertoire surcharge."""

    parent_dir: Path
    current_count: int
    max_allowed: int
    ranges: list[tuple[str, str]]
    items_to_move: list[tuple[Path, Path]]
    out_of_range_items: list[tuple[Path, Path]] = field(default_factory=list)


@dataclass
class CleanupReport:
    """Rapport complet d'analyse du repertoire video."""

    video_dir: Path
    broken_symlinks: list[BrokenSymlinkInfo]
    misplaced_symlinks: list[MisplacedSymlink]
    oversized_dirs: list[SubdivisionPlan]
    empty_dirs: list[Path]
    duplicate_symlinks: list[DuplicateSymlink] = field(default_factory=list)
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
            + len(self.duplicate_symlinks)
            + len(self.oversized_dirs)
            + len(self.empty_dirs)
        )


@dataclass
class CleanupResult:
    """Resultat de l'execution des corrections."""

    repaired_symlinks: int = 0
    failed_repairs: int = 0
    broken_symlinks_deleted: int = 0
    moved_symlinks: int = 0
    duplicate_symlinks_removed: int = 0
    subdivisions_created: int = 0
    symlinks_redistributed: int = 0
    empty_dirs_removed: int = 0
    errors: list[str] = field(default_factory=list)
