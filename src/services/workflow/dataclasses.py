"""
Dataclasses et enums du workflow de traitement des videos.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from src.core.entities.video import PendingValidation

if TYPE_CHECKING:
    from src.adapters.cli.validation import ConflictResolution


class WorkflowStep(str, Enum):
    """Étapes du workflow."""

    CLEANUP_ORPHANS = "cleanup_orphans"
    SCAN_DOWNLOADS = "scan_downloads"
    MATCHING = "matching"
    AUTO_VALIDATION = "auto_validation"
    MANUAL_VALIDATION = "manual_validation"
    BATCH_TRANSFER = "batch_transfer"
    SUMMARY = "summary"


@dataclass
class WorkflowConfig:
    """Configuration du workflow."""

    filter_type: str = "all"  # all, movies, series
    dry_run: bool = False
    storage_dir: Path = field(default_factory=lambda: Path("."))
    video_dir: Path = field(default_factory=lambda: Path("."))

    # Répertoires de staging pour les conflits
    video_staging_dir: Optional[Path] = None
    storage_staging_dir: Optional[Path] = None

    def __post_init__(self):
        if self.video_staging_dir is None:
            self.video_staging_dir = self.video_dir.parent / "staging"
        if self.storage_staging_dir is None:
            self.storage_staging_dir = self.storage_dir / "staging"


@dataclass
class WorkflowState:
    """État du workflow pendant son exécution."""

    # Résultats intermédiaires
    scan_results: list = field(default_factory=list)
    undersized_results: list = field(default_factory=list)
    pending_validations: list[PendingValidation] = field(default_factory=list)

    # IDs créés pour nettoyage dry-run
    created_video_file_ids: list[str] = field(default_factory=list)

    # Compteurs
    orphan_count: int = 0
    auto_validated_count: int = 0
    manual_validated_count: int = 0

    # Transferts construits
    transfers: list[dict] = field(default_factory=list)

    # Résolution de conflits (cache)
    conflict_decisions: dict[str, "ConflictResolution"] = field(default_factory=dict)


@dataclass
class WorkflowResult:
    """Résultat final du workflow."""

    success: bool
    state: WorkflowState
    errors: list[str] = field(default_factory=list)

    @property
    def total_processed(self) -> int:
        """Nombre total de fichiers traités."""
        return len(self.state.scan_results)

    @property
    def total_validated(self) -> int:
        """Nombre total de fichiers validés."""
        return self.state.auto_validated_count + self.state.manual_validated_count
