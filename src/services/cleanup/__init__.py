"""
Package de nettoyage et reorganisation du repertoire video.

Reexporte CleanupService, les dataclasses et les fonctions de cache
pour preserver la compatibilite des imports existants.
"""

from .cleanup_service import CleanupService
from .dataclasses import (
    MANAGED_SUBDIRS,
    BrokenSymlinkInfo,
    CleanupReport,
    CleanupResult,
    CleanupStepType,
    DuplicateSymlink,
    MisplacedSymlink,
    SubdivisionPlan,
)
from .report_cache import load_report_cache, save_report_cache
from .subdivision_algorithm import (
    _find_sibling_for_key,
    _normalize_sort_key,
    _parse_parent_range,
    _refine_out_of_range_dest,
    _refine_plans_destinations,
)

__all__ = [
    "CleanupService",
    "CleanupStepType",
    "BrokenSymlinkInfo",
    "MisplacedSymlink",
    "DuplicateSymlink",
    "SubdivisionPlan",
    "CleanupReport",
    "CleanupResult",
    "MANAGED_SUBDIRS",
    "save_report_cache",
    "load_report_cache",
    "_normalize_sort_key",
    "_parse_parent_range",
    "_find_sibling_for_key",
    "_refine_out_of_range_dest",
    "_refine_plans_destinations",
]
