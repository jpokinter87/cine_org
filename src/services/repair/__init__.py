"""
Package de reparation des symlinks casses.

Reexporte RepairService et les classes auxiliaires pour
preserver la compatibilite des imports existants.
"""

from .file_indexer import FileIndexer
from .filename_analyzer import extract_clean_title, extract_series_info, normalize_filename
from .repair_service import RepairService
from .similarity_matcher import calculate_similarity_fast, calculate_title_similarity

__all__ = [
    "RepairService",
    "FileIndexer",
    "normalize_filename",
    "extract_clean_title",
    "extract_series_info",
    "calculate_similarity_fast",
    "calculate_title_similarity",
]
