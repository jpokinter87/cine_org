"""Sous-package CLI commands - re-exporte toutes les commandes."""

from src.adapters.cli.commands.workflow_commands import (
    MediaFilter,
    process,
    pending,
    _process_async,
    _pending_async,
    _render_pending_panel,
)
from src.adapters.cli.commands.validate_commands import (
    validate_app,
    validate_auto,
    validate_manual,
    validate_batch,
    validate_file,
    _validate_auto_async,
    _validate_manual_async,
    _validate_batch_async,
    _validate_file_async,
)
from src.adapters.cli.commands.import_commands import (
    import_library,
    enrich,
    populate_movies,
    _import_library_async,
    _enrich_async,
    _populate_movies_async,
)
from src.adapters.cli.commands.enrichment_commands import (
    enrich_ratings,
    enrich_imdb_ids,
    _enrich_ratings_async,
    _enrich_imdb_ids_async,
)
from src.adapters.cli.commands.imdb_commands import (
    imdb_app,
    imdb_import,
    imdb_sync,
    imdb_stats,
    _imdb_import_async,
    _imdb_sync_async,
    _imdb_stats_async,
)
from src.adapters.cli.commands.maintenance_commands import (
    repair_links,
    consolidate,
    check,
    cleanup,
    regroup,
    _repair_links_async,
    _cleanup_async,
    _regroup_async,
)

__all__ = [
    # workflow
    "MediaFilter",
    "process",
    "pending",
    "_process_async",
    "_pending_async",
    "_render_pending_panel",
    # validate
    "validate_app",
    "validate_auto",
    "validate_manual",
    "validate_batch",
    "validate_file",
    "_validate_auto_async",
    "_validate_manual_async",
    "_validate_batch_async",
    "_validate_file_async",
    # import
    "import_library",
    "enrich",
    "populate_movies",
    "_import_library_async",
    "_enrich_async",
    "_populate_movies_async",
    # enrichment
    "enrich_ratings",
    "enrich_imdb_ids",
    "_enrich_ratings_async",
    "_enrich_imdb_ids_async",
    # imdb
    "imdb_app",
    "imdb_import",
    "imdb_sync",
    "imdb_stats",
    "_imdb_import_async",
    "_imdb_sync_async",
    "_imdb_stats_async",
    # maintenance
    "repair_links",
    "consolidate",
    "check",
    "cleanup",
    "regroup",
    "_repair_links_async",
    "_cleanup_async",
    "_regroup_async",
]
