"""Sous-package CLI commands - re-exporte les commandes publiques."""

from src.adapters.cli.commands.workflow_commands import (
    MediaFilter,
    process,
    pending,
)
from src.adapters.cli.commands.validate_commands import (
    validate_app,
    validate_auto,
    validate_manual,
    validate_batch,
    validate_file,
)
from src.adapters.cli.commands.import_commands import (
    clean_titles,
    enrich_episode_titles,
    enrich_tech,
    enrich_tvdb_ids,
    import_library,
    enrich,
    link_movies,
    populate_movies,
    populate_series,
)
from src.adapters.cli.commands.enrichment_commands import (
    enrich_collections,
    enrich_ratings,
    enrich_imdb_ids,
    enrich_series,
    enrich_movies_credits,
)
from src.adapters.cli.commands.imdb_commands import (
    imdb_app,
    imdb_import,
    imdb_sync,
    imdb_stats,
)
from src.adapters.cli.commands.repair_command import (
    repair_links,
)
from src.adapters.cli.commands.consolidate_command import (
    consolidate,
)
from src.adapters.cli.commands.check_command import (
    check,
)
from src.adapters.cli.commands.cleanup_command import (
    cleanup,
)
from src.adapters.cli.commands.regroup_command import (
    regroup,
)
from src.adapters.cli.commands.fix_bad_links_command import (
    fix_bad_links,
)
from src.adapters.cli.commands.fix_symlinks_command import (
    fix_symlinks,
)
from src.adapters.cli.commands.reconcile_command import (
    reconcile,
)
from src.adapters.cli.commands.migrate_series_command import (
    migrate_series,
)
from src.adapters.cli.commands.migrate_nas_command import (
    migrate_nas_app,
)
from src.adapters.cli.commands.fix_series_symlinks_command import (
    fix_series_symlinks,
)
from src.adapters.cli.commands.duplicates_command import (
    check_duplicates,
)
from src.adapters.cli.commands.hardlink_commands import (
    purge_hardlinks,
)
from src.adapters.cli.commands.rename_canonical_command import (
    rename_canonical,
)
from src.adapters.cli.commands.reclassify_shorts_command import (
    reclassify_shorts,
)
from src.adapters.cli.commands.collections_command import (
    collections_app,
)
from src.adapters.cli.commands.check_missing_files_command import (
    check_missing_files,
)

__all__ = [
    # workflow
    "MediaFilter",
    "process",
    "pending",
    # validate
    "validate_app",
    "validate_auto",
    "validate_manual",
    "validate_batch",
    "validate_file",
    # import
    "import_library",
    "enrich",
    "link_movies",
    "populate_movies",
    "populate_series",
    # enrichment
    "enrich_ratings",
    "enrich_imdb_ids",
    "enrich_series",
    "enrich_movies_credits",
    "enrich_collections",
    # imdb
    "imdb_app",
    "imdb_import",
    "imdb_sync",
    "imdb_stats",
    # maintenance
    "repair_links",
    "consolidate",
    "check",
    "cleanup",
    "regroup",
    "fix_symlinks",
    "fix_bad_links",
    "clean_titles",
    "enrich_tech",
    "enrich_episode_titles",
    "enrich_tvdb_ids",
    "reconcile",
    "migrate_series",
    "migrate_nas_app",
    "fix_series_symlinks",
    "check_duplicates",
    "purge_hardlinks",
    "rename_canonical",
    "reclassify_shorts",
    "collections_app",
    "check_missing_files",
]
