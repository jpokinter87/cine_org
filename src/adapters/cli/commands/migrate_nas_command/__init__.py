"""
Commande CLI `migrate-nas` : migration filtrée d'anciens NAS vers le nouveau.

Trois sous-commandes :

* `plan` : scanne une arborescence source, classe chaque fichier par note
  combinée IMDb/TMDB/personnelle, écrit un plan JSON et trois CSV de revue
  (low_rated, unrated, broken). Aucune opération destructive.
* `apply` : consomme un plan JSON, lance les transferts via rsync (sans
  --remove-source-files), vérifie l'intégrité xxh3_64 et swappe les
  symlinks. Reprenable via un state store SQLite.
* `status` : affiche l'état d'avancement (par bucket et par TransferStatus).

Architecture interne (post-refactor B#5) :

* `commands.py` — wiring Typer (sous-commandes `plan`/`apply`/`status`)
  et helper d'affichage `_display_plan_summary`.
* `orchestrators.py` — helpers métier `build_plan`/`run_apply`/`run_status`,
  testables sans Typer (injection de FakeRsync, session in-memory, etc.).
* `progress_ui.py` — barres Rich (`_build_with_progress`,
  `_execute_with_progress`) + classe `_PhaseTracker` qui encapsule l'état
  courant du transfert (phase, compteur committed) — remplace l'ancien
  pattern dict-as-cell utilisé en closures.

Re-exports : on garde la même surface publique que l'ancien module monolithique
pour ne casser aucun import existant (commands/__init__.py, tests).
"""

from src.adapters.cli.commands.migrate_nas_command.commands import (
    migrate_nas_app,
)
from src.adapters.cli.commands.migrate_nas_command.orchestrators import (
    build_plan,
    run_apply,
    run_status,
)

__all__ = [
    "build_plan",
    "migrate_nas_app",
    "run_apply",
    "run_status",
]
