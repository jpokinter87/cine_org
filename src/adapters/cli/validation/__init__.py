"""
Package CLI de validation interactive avec Rich.

Reexporte les symboles principaux pour preserver la compatibilite
des imports existants (from src.adapters.cli.validation import ...).
"""

from rich.console import Console

# Console globale pour tous les affichages
console = Console()

from .batch_display import (
    ConflictResolution,
    display_batch_summary,
    display_similar_content_conflict,
    execute_batch_transfer,
    format_file_size,
    prompt_conflict_resolution,
)
from .candidate_display import (
    CandidatePaginator,
    display_candidates,
    display_enriched_candidates,
    display_help,
    format_duration,
    render_candidate_card,
    render_enriched_candidate_card,
)
from .interactive_loop import (
    IMDB_PATTERN,
    SERIES_PATTERNS,
    detect_external_id,
    determine_is_series,
    validation_loop,
)

__all__ = [
    "console",
    "CandidatePaginator",
    "ConflictResolution",
    "render_candidate_card",
    "render_enriched_candidate_card",
    "display_candidates",
    "display_enriched_candidates",
    "display_help",
    "format_duration",
    "format_file_size",
    "display_similar_content_conflict",
    "prompt_conflict_resolution",
    "display_batch_summary",
    "execute_batch_transfer",
    "detect_external_id",
    "determine_is_series",
    "validation_loop",
    "IMDB_PATTERN",
    "SERIES_PATTERNS",
]
