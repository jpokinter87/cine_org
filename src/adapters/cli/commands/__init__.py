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
    import_library,
    enrich,
    link_movies,
    populate_movies,
    populate_series,
)
from src.adapters.cli.commands.enrichment_commands import (
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
]
