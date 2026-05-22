"""
Helpers d'affichage Rich pour la commande `migrate-nas`.

Encapsule les barres de progression utilisées par les sous-commandes
`plan` (via `_build_with_progress`) et `apply` (via `_PhaseTracker` +
`_execute_with_progress`).

`_PhaseTracker` capture l'état du transfert en cours (phase courante,
nombre d'items committed) et expose des callbacks compatibles avec
`MigrationTransferExecutor.on_event` / `on_rsync_progress`. Remplace
le pattern dict-as-cell utilisé précédemment dans des closures imbriquées.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from rich.markup import escape as rich_escape
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from src.adapters.cli.validation import console
from src.services.migration.dataclasses import (
    Bucket,
    MigrationItem,
    MigrationPlan,
    TransferOutcome,
)
from src.services.migration.plan_builder import MigrationPlanBuilder
from src.services.migration.scanner import MigrationScanner
from src.services.migration.state_store import MigrationStateStore
from src.services.migration.transfer_executor import (
    MigrationTransferExecutor,
    RsyncRunner,
)


# ---- Mapping events transfer_executor → phases canoniques affichées --------


_PHASES_FR: tuple[str, ...] = (
    "préparation",
    "copie",
    "vérification",
    "finalisation",
    "commit",
)


def _canonical_phase(emit_phase: str) -> Optional[str]:
    """Mappe un event émis par transfer_executor sur l'une des 5 phases
    canoniques affichées (ou None pour `start` qui conserve la phase
    précédente pour ne pas casser le highlight).

    Phases émises par MigrationTransferExecutor : start, preparing,
    hashing_source, hashing_existing, copying_attempt_N, retry_pause_Ns,
    verifying, finalizing, committed.
    """
    if emit_phase in ("preparing", "hashing_source", "hashing_existing"):
        return "préparation"
    if emit_phase.startswith("copying_") or emit_phase.startswith(
        "retry_pause_"
    ):
        return "copie"
    if emit_phase == "verifying":
        return "vérification"
    if emit_phase == "finalizing":
        return "finalisation"
    if emit_phase == "committed":
        return "commit"
    return None


def _render_phase_sequence(current: Optional[str]) -> str:
    """Construit la ligne de séquence des phases avec markup Rich. La phase
    courante est en rouge gras et capitalisée ; les autres en `dim`."""
    parts = []
    for p in _PHASES_FR:
        if p == current:
            parts.append(f"[bold red]{p.upper()}[/bold red]")
        else:
            parts.append(f"[dim]{p}[/dim]")
    return f"Phases : {' [dim]→[/dim] '.join(parts)}"


def _phase_label_from_emit(phase: str) -> str:
    """Convertit un event en label lisible (sans crochets Rich)."""
    if phase == "start":
        return "démarrage"
    if phase == "preparing":
        return "préparation (DB)"
    if phase == "hashing_source":
        return "hash source (xxh3_64) — peut prendre du temps"
    if phase == "hashing_existing":
        return "hash dest (vérif reprise)"
    if phase.startswith("copying_attempt_"):
        n = phase.rsplit("_", 1)[1]
        return f"copie (essai {n})"
    if phase.startswith("retry_pause_"):
        secs = phase.removeprefix("retry_pause_").rstrip("s")
        return f"pause {secs}s avant nouvel essai"
    if phase.startswith("rsync_error:"):
        msg = phase.removeprefix("rsync_error:")[:80]
        return f"ERREUR rsync : {msg}"
    if phase == "verifying":
        return "vérification hash"
    if phase == "finalizing":
        return "finalisation (symlink + suppression source)"
    return phase


# ---- _PhaseTracker : encapsule l'état des barres pendant `apply` -----------


class _PhaseTracker:
    """Encapsule l'état de progression d'un transfert en cours.

    Remplace le pattern dict-as-cell (`current_phase = {"label": ...}`) par
    une classe avec attributs nommés. Expose `on_event` et `on_rsync_progress`
    directement utilisables comme callbacks de MigrationTransferExecutor.
    """

    def __init__(
        self,
        *,
        progress: Progress,
        phase_task,
        item_task,
        file_task,
        total: int,
    ) -> None:
        self._progress = progress
        self._phase_task = phase_task
        self._item_task = item_task
        self._file_task = file_task
        self._total = total
        self._canonical: Optional[str] = None
        self._current_label: str = "starting"
        self._committed: int = 0

    @property
    def committed(self) -> int:
        return self._committed

    def _refresh_phase_task(self, emit_phase: str) -> None:
        canonical = _canonical_phase(emit_phase)
        if canonical and canonical != self._canonical:
            self._canonical = canonical
            self._progress.update(
                self._phase_task, description=_render_phase_sequence(canonical)
            )

    def on_event(self, item: MigrationItem, phase: str) -> None:
        size_mb = (item.size_bytes or 0) / (1024**2)
        # rich_escape protège contre les filenames type
        # "Movie [1080p][x265].mkv" qui casseraient le markup Rich.
        short = rich_escape(item.symlink_path.name[:55])
        if phase == "start":
            self._progress.update(
                self._file_task,
                total=max(item.size_bytes or 1, 1),
                completed=0,
                description=f"[file] {short}",
                visible=True,
            )
        self._refresh_phase_task(phase)
        if phase == "committed":
            self._committed += 1
            self._current_label = "committed"
            self._progress.update(
                self._item_task,
                advance=1,
                description=(
                    f"[green]✓[/green] {short} "
                    f"({self._committed}/{self._total})"
                ),
            )
            self._progress.update(self._file_task, visible=False)
            return
        self._current_label = _phase_label_from_emit(phase)
        label = rich_escape(self._current_label)
        self._progress.update(
            self._item_task,
            description=f"\\[{label}] {short} ({size_mb:.0f} MB)",
        )

    def on_rsync_progress(
        self, item: MigrationItem, bytes_done: int, percent: int, speed: str
    ) -> None:
        """Mise a jour live pendant le rsync (via --info=progress2)."""
        short = rich_escape(item.symlink_path.name[:50])
        speed_safe = rich_escape(speed)
        self._progress.update(self._file_task, completed=bytes_done)
        self._progress.update(
            self._item_task,
            description=f"\\[rsync {speed_safe:>10s}] {short}",
        )


# ---- Wrappers haut niveau qui setup les barres + délègue à l'executor ------


def _build_with_progress(
    builder: MigrationPlanBuilder,
    scanner: MigrationScanner,
    source_root: Path,
    destination_root: Path,
) -> MigrationPlan:
    """Lance build() en affichant une barre de progression Rich.

    Pré-compte les fichiers vidéo (rapide : juste un walk filesystem) puis
    relance le scanner avec une barre qui suit chaque candidat traité, le
    nom courant, et la ventilation par bucket en temps réel.
    """
    # Désactiver loguru pendant l'affichage Rich (mémoire CineOrg).
    from loguru import logger as loguru_logger

    loguru_logger.disable("src")
    try:
        console.print("[dim]Comptage initial des fichiers vidéo…[/dim]")
        # `count_files` fait un walk pur sans extraction mediainfo ni
        # résolution de symlinks — sinon le comptage paye 2x le coût total.
        total = scanner.count_files(source_root)
        console.print(
            f"[dim]{total} fichier(s) vidéo détecté(s) — démarrage du plan.[/dim]"
        )
        console.print(
            "[dim]Légende buckets : "
            "[bold]M[/bold]igrate · "
            "[bold]L[/bold]ow_rated · "
            "[bold]U[/bold]nrated · "
            "needs_[bold]V[/bold]alidation · "
            "[bold]P[/bold]résent (déjà en DB) · "
            "[bold]B[/bold]roken · "
            "[bold]A[/bold]lready_on_destination"
            "[/dim]\n"
        )

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]{task.description}"),
            BarColumn(bar_width=40),
            MofNCompleteColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            TextColumn("•"),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Scan & classification", total=total)

            def on_progress(item, stats) -> None:
                progress.update(
                    task,
                    advance=1,
                    description=(
                        f"M={stats.to_migrate} L={stats.low_rated} U={stats.unrated} "
                        f"V={stats.needs_validation} P={stats.already_in_library} "
                        f"B={stats.broken} A={stats.already_on_destination}"
                    ),
                )

            return builder.build(
                source_root, destination_root, on_progress=on_progress
            )
    finally:
        loguru_logger.enable("src")


def _execute_with_progress(
    *,
    plan: MigrationPlan,
    store: MigrationStateStore,
    rsync_runner: Optional[RsyncRunner],
    max_retries: int,
    retry_pause_seconds: int,
    raw_finalizer,
    verify_hash: bool = True,
) -> list[TransferOutcome]:
    """Exécute les transferts avec barre de progression Rich + _PhaseTracker."""
    from loguru import logger as loguru_logger

    pending_ids = set(store.pending_items())
    pending_items = [
        i
        for i in plan.items
        if i.bucket == Bucket.MIGRATE and i.item_id in pending_ids
    ]
    total = len(pending_items)
    total_size_gb = sum(i.size_bytes or 0 for i in pending_items) / (1024**3)
    if total == 0:
        console.print("[yellow]Aucun item à transférer (tous déjà committed).[/yellow]")
        return []

    console.print(
        f"[cyan]{total} item(s) pending — volume estimé : "
        f"[bold]{total_size_gb:.1f} GB[/bold][/cyan]"
    )

    loguru_logger.disable("src")
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            BarColumn(bar_width=30),
            MofNCompleteColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            TextColumn("•"),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            # Ligne phases : sequence des 5 phases canoniques avec phase
            # courante en rouge gras. start=False désactive le spinner
            # auto sur cette task (visuellement statique entre updates).
            phase_task = progress.add_task(
                _render_phase_sequence(None), total=None, start=False
            )
            item_task = progress.add_task("Démarrage…", total=total)
            # Sous-barre dédiée au fichier en cours : total = taille du
            # fichier, completed = octets transférés via on_rsync_progress.
            file_task = progress.add_task(
                "(en attente)", total=1, visible=False
            )

            tracker = _PhaseTracker(
                progress=progress,
                phase_task=phase_task,
                item_task=item_task,
                file_task=file_task,
                total=total,
            )

            executor = MigrationTransferExecutor(
                plan=plan,
                state_store=store,
                rsync_runner=rsync_runner,
                max_retries=max_retries,
                retry_pause_seconds=retry_pause_seconds,
                raw_finalizer=raw_finalizer,
                on_event=tracker.on_event,
                on_rsync_progress=tracker.on_rsync_progress,
                verify_hash=verify_hash,
            )
            return executor.execute_all()
    finally:
        loguru_logger.enable("src")
