"""
Sous-commande `migrate-nas review` : review interactive des items en attente.

Itère sur les 4 buckets non-MIGRATE (needs_validation, unrated, low_rated,
already_in_library), affiche une carte Rich par item, prompt l'utilisateur
pour une décision. Décisions persistées dans state_store, consultables
ensuite par `migrate-nas apply`.

Reprise via --resume (skippe les items déjà décidés).
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from src.adapters.cli.validation import console
from src.container import Container
from src.services.duplicate_detector import DuplicateDetector
from src.services.matcher import MatcherService
from src.services.migration._helpers import is_series_like
from src.services.migration.dataclasses import Bucket, MigrationItem
from src.services.migration.decisions import DecisionStatus
from src.services.migration.plan_builder import deserialize_plan
from src.services.migration.review_service import (
    MigrationReviewService,
    REVIEW_BUCKETS,
)
from src.services.migration.state_store import MigrationStateStore


def _print_summary(
    service: MigrationReviewService,
    plan_path: Path,
    state_path: Path,
) -> None:
    """Affiche le résumé final + URL web si items deferred."""
    summary = service.summary()
    console.print()
    console.print("─" * 60)
    console.print("[bold]Session review terminée[/bold]")
    console.print(f"  Total review buckets : {summary['total_review_buckets']}")
    console.print(f"  [green]✓[/green] Approuvés : {summary.get('approved', 0)}")
    console.print(f"  [yellow]⊘[/yellow] Skippés  : {summary.get('skipped', 0)}")
    console.print(f"  [red]✗[/red] Rejetés   : {summary.get('rejected', 0)}")
    deferred = summary.get("deferred_to_web", 0)
    if deferred:
        console.print(
            f"  [cyan]↗[/cyan] Déférés web : {deferred}"
            f"\n      → http://localhost:8000/migration/review?plan={plan_path}"
        )
    pending = summary.get("pending", 0)
    total_review = summary.get("total_review_buckets", 0)
    decided_in_plan = sum(
        summary.get(s, 0)
        for s in ("approved", "skipped", "rejected", "deferred_to_web")
    )
    if pending:
        console.print(f"  [dim]En attente : {pending} (--resume pour reprendre)[/dim]")
    elif total_review > 0:
        if decided_in_plan == 0:
            # Tous les items review du plan ont été sautés par --resume
            # (décisions héritées d'une session antérieure). Cas typique :
            # re-génération d'un plan sur les mêmes sources.
            console.print(
                f"[yellow]Aucun item à reviewer dans ce plan ({total_review} items "
                f"déjà décidés via --resume).[/yellow]\n"
                f"Utilise [bold]--restart[/bold] pour les re-traiter ou "
                f"[bold]migrate-nas apply {plan_path}[/bold] pour transférer "
                f"directement les approuvés."
            )
        else:
            console.print(
                "[green]Tous les items ont une décision.[/green] "
                f"Lance [bold]migrate-nas apply {plan_path}[/bold] pour transférer "
                "les approuvés."
            )
    console.print("─" * 60)


_REVIEW_EVENT_LOOP: Optional[asyncio.AbstractEventLoop] = None


def _review_run_async(coro):
    """Exécute une coroutine sur l'event loop persistant de la review.

    Pourquoi : `asyncio.run()` crée ET ferme un loop à chaque appel.
    Les ressources async du TMDBClient (httpx AsyncClient + connection
    pool) restent attachées au premier loop ; le 2e `asyncio.run()`
    crée un nouveau loop qui essaie de réutiliser le pool fermé, d'où
    `RuntimeError: Event loop is closed`. On garde un seul loop pour
    toute la durée de la commande review.
    """
    global _REVIEW_EVENT_LOOP
    if _REVIEW_EVENT_LOOP is None or _REVIEW_EVENT_LOOP.is_closed():
        _REVIEW_EVENT_LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(_REVIEW_EVENT_LOOP)
    return _REVIEW_EVENT_LOOP.run_until_complete(coro)


def _close_review_event_loop() -> None:
    """Ferme proprement le loop review (appelé en fin de commande)."""
    global _REVIEW_EVENT_LOOP
    if _REVIEW_EVENT_LOOP is not None and not _REVIEW_EVENT_LOOP.is_closed():
        _REVIEW_EVENT_LOOP.close()
    _REVIEW_EVENT_LOOP = None


def review_command(
    plan_path: Annotated[
        Path,
        typer.Argument(
            help=(
                "Chemin du plan JSON produit par `plan`. "
                "Défaut : ./migration/plan.json (convention de l'app)."
            ),
        ),
    ] = Path("./migration/plan.json"),
    bucket: Annotated[
        Optional[str],
        typer.Option(
            "--bucket",
            help=(
                "Filtre sur un bucket précis (needs_validation, unrated, "
                "low_rated, already_in_library). Défaut : tous."
            ),
        ),
    ] = None,
    resume: Annotated[
        bool,
        typer.Option(
            "--resume/--restart",
            help=(
                "Reprend en sautant les items déjà décidés (défaut). "
                "--restart force le re-traitement de tous."
            ),
        ),
    ] = True,
    state_store: Annotated[
        Optional[Path],
        typer.Option(
            "--state-store",
            help="Chemin du journal SQLite (défaut: <plan>.state.sqlite).",
        ),
    ] = None,
) -> None:
    """Review interactive des items en attente (4 buckets non-MIGRATE)."""
    # Valider les arguments (fail fast sur bad args avant tout I/O).
    try:
        bucket_filter = Bucket(bucket) if bucket else None
    except ValueError as e:
        valid = ", ".join(b.value for b in Bucket)
        raise typer.BadParameter(
            f"Bucket invalide : '{bucket}'. Valeurs autorisées : {valid}",
            param_hint="--bucket",
        ) from e
    if not plan_path.exists():
        console.print(
            f"[red]Plan introuvable :[/red] {plan_path}\n"
            f"[dim]Génère-le avec `cineorg migrate-nas plan --source ... --output {plan_path}`.[/dim]"
        )
        raise typer.Exit(code=1)
    state_path = state_store or plan_path.with_suffix(
        plan_path.suffix + ".state.sqlite"
    )
    console.print(
        f"[bold cyan]Review[/bold cyan] depuis [yellow]{plan_path}[/yellow] "
        f"(state: [dim]{state_path}[/dim], "
        f"bucket: {bucket_filter.value if bucket_filter else 'tous'}, "
        f"resume: {resume})"
    )
    store = MigrationStateStore(state_path)
    try:
        service = _build_review_service(plan_path, store)
        items = list(service.iter_pending(bucket=bucket_filter, resume=resume))
        total = len(items)
        if total == 0:
            console.print("[yellow]Aucun item en attente — rien à reviewer.[/yellow]")
            _print_summary(service, plan_path, state_path)
            return
        # Snapshot des décisions à l'entrée de la session : permet de ne skipper
        # que celles ajoutées EN COURS (cas typique : cascade bulk-accept série
        # qui décide plusieurs épisodes d'un coup). Sans snapshot, --restart
        # serait inopérant — la boucle re-skipperait sur les décisions
        # historiques que --restart cherche justement à re-traiter.
        decisions_at_start = set(store.load_decisions().keys())
        for idx, item in enumerate(items, start=1):
            already = store.get_decision(item.item_id)
            if already is not None and item.item_id not in decisions_at_start:
                continue
            while True:
                render_review_card(console, item, position=(idx, total))
                if item.bucket == Bucket.NEEDS_VALIDATION:
                    result = _handle_needs_validation(service, item)
                elif item.bucket == Bucket.UNRATED:
                    result = _handle_unrated(service, item)
                elif item.bucket == Bucket.LOW_RATED:
                    result = _handle_low_rated(service, item)
                elif item.bucket == Bucket.ALREADY_IN_LIBRARY:
                    result = _handle_already_in_library(service, item)
                else:
                    console.print(
                        f"[yellow]Bucket {item.bucket.value} non géré (inattendu).[/yellow]"
                    )
                    result = "continue"
                if result == "quit":
                    console.print("\n[cyan]Sortie demandée.[/cyan]")
                    _print_summary(service, plan_path, state_path)
                    return
                if result == "continue":
                    break
                # "redraw" → re-affiche le même item
        _print_summary(service, plan_path, state_path)
    finally:
        store.close()
        _close_review_event_loop()


def _build_review_service(
    plan_path: Path,
    store: MigrationStateStore,
) -> MigrationReviewService:
    """Câble le ReviewService depuis le container (le store est fourni).

    Le `imdb_aka_searcher` est branché en best-effort : si la table
    `imdb_akas` est absente ou vide, le fallback reste inerte (le service
    appelle search_akas et reçoit []). L'utilisateur active la feature
    en lançant `cineorg imdb import-akas` une fois.
    """
    plan = deserialize_plan(plan_path.read_text(encoding="utf-8"))
    container = Container()
    return MigrationReviewService(
        plan=plan,
        state_store=store,
        tmdb_client=container.tmdb_client(),
        tvdb_client=container.tvdb_client(),
        matcher=MatcherService(),
        duplicate_detector=DuplicateDetector(),
        imdb_aka_searcher=_build_imdb_aka_searcher(),
    )


def _build_imdb_aka_searcher():
    """Construit un IMDbDatasetImporter branché sur la session DB courante,
    ou None si l'init échoue (table absente, etc.). Le service le tolère."""
    try:
        from src.adapters.imdb.dataset_importer import IMDbDatasetImporter
        from src.infrastructure.persistence.database import get_session

        container = Container()
        config = container.config()
        session = next(get_session())
        return IMDbDatasetImporter(
            cache_dir=Path(getattr(config, "imdb_cache_dir", ".cache/imdb")),
            session=session,
        )
    except Exception:  # noqa: BLE001 — fallback désactivé en cas d'erreur init
        return None


def _collision_tmdb_id(item: MigrationItem) -> Optional[str]:
    """Retourne l'id de collision_tmdb tag si présent, sinon None."""
    for tag in item.tags:
        if tag.startswith("collision_tmdb:"):
            return tag.split(":", 1)[1]
    return None


def _existing_path_from_tag(item: MigrationItem) -> Optional[Path]:
    """Extrait le chemin de la version DB depuis le tag existing:<path>."""
    for tag in item.tags:
        if tag.startswith("existing:"):
            return Path(tag.split(":", 1)[1])
    return None


def _items_in_collision_group(plan, group_id: str) -> list:
    """Retourne tous les items du plan partageant ce collision_tmdb id.

    Filtré sur REVIEW_BUCKETS : les items qui ont déjà été promus en MIGRATE
    (ou tombés en BROKEN/etc.) ne doivent pas recevoir de décision review.
    """
    return [
        it for it in plan.items
        if f"collision_tmdb:{group_id}" in it.tags
        and it.bucket in REVIEW_BUCKETS
    ]


def _maybe_bulk_accept_collision(
    service: MigrationReviewService,
    item: MigrationItem,
    chosen: dict,
) -> bool:
    """Si l'item fait partie d'un groupe collision_tmdb, propose accept en masse.

    Retourne True si bulk-accept appliqué (caller doit alors continue), False
    si user a refusé (caller fait le single-accept normal).
    """
    group_id = _collision_tmdb_id(item)
    if group_id is None:
        return False
    siblings = _items_in_collision_group(service._plan, group_id)
    if len(siblings) < 2:
        return False
    if not Confirm.ask(
        f"[cyan]🔗 Multi-parts détecté ({len(siblings)} items, "
        f"tag collision_tmdb:{group_id}). Accepter pour les {len(siblings)} ?"
        f"[/cyan]",
        default=True,
    ):
        return False
    base_title = chosen.get("title", "Untitled")
    for n, sibling in enumerate(siblings, start=1):
        sibling_chosen = dict(chosen)
        sibling_chosen["title"] = f"{base_title} - Part {n}"
        _persist_approved(service, sibling, sibling_chosen)
    return True


def _is_series_item(item: MigrationItem) -> bool:
    """True si l'item est probablement un épisode de série / animation.

    Délégué à `is_series_like` (partagé avec `raw_finalizer`).
    """
    return is_series_like(item.media_root, item.symlink_path)


def _default_search_query(item: MigrationItem) -> str:
    """Calcule un titre par défaut pour pré-remplir le prompt de recherche.

    - Pour les séries : nom du dossier parent (avec ' Saison N' retiré).
      Évite que guessit renvoie le titre d'épisode plutôt que celui de la série.
    - Pour les films : titre parsé par guessit depuis le nom de fichier,
      avec année si disponible.
    - Fallback : nom de fichier sans extension.
    """
    import re as _re

    from guessit import guessit

    if item.symlink_path is None:
        return ""

    if _is_series_item(item):
        parent_name = item.symlink_path.parent.name
        series = _re.sub(r"\s*[Ss]aison\s+\d+\s*$", "", parent_name).strip()
        if series:
            return series
        # Pas de "Saison N" parsable → fallback guessit

    try:
        parsed = guessit(item.symlink_path.name, {"type": "movie"})
        title = parsed.get("title")
        year = parsed.get("year")
        if title:
            return f"{title} {year}" if year else str(title)
    except Exception:  # noqa: BLE001 — guessit best-effort
        pass
    return item.symlink_path.stem


def _split_query_year(query: str) -> tuple[str, Optional[int]]:
    """Extrait l'année (4 chiffres, 1900-2099) à la fin du query si présente.

    Retourne (query_sans_année, année) ou (query, None). Permet de passer
    `year=` à TMDB plutôt que de noyer l'année dans le texte (meilleur
    ranking sur les homonymes).
    """
    m = re.search(r"\s+(19\d{2}|20\d{2})\s*$", query)
    if m is None:
        return query, None
    return query[: m.start()].strip(), int(m.group(1))


def _series_group_key(item: MigrationItem) -> Optional[str]:
    """Retourne une clé identifiant la série pour la cascade, ou None.

    Détecte une série de 2 façons :
    - via `item.media_root` (cas simple : scanner a identifié la catégorie)
    - via le chemin (cas nested : NAS avec wrapper top-level, ex.
      /media/wd10-1/Vidéothèque10/Animations/...)

    Pour les items détectés série, regroupe par nom de série en retirant
    le suffixe ' Saison N' du dossier parent. Toutes les saisons d'une
    même série partagent ainsi la même clé.
    """
    if not _is_series_item(item):
        return None

    assert item.symlink_path is not None  # garanti par _is_series_item
    parent = item.symlink_path.parent
    parent_name = parent.name
    # Retire suffixe " Saison N" pour clusteriser toutes les saisons
    series_name = re.sub(r"\s*[Ss]aison\s+\d+\s*$", "", parent_name).strip()
    if not series_name:
        return str(parent.parent)
    return str(parent.parent / series_name)


def _items_in_series_group(
    plan,
    group_key: str,
    *,
    excluding_id: Optional[str] = None,
) -> list:
    """Retourne tous les items du plan dans la même série, hors excluding_id.

    Filtre sur REVIEW_BUCKETS : les items MIGRATE/BROKEN ne reçoivent pas
    de décision review.
    """
    out = []
    for it in plan.items:
        if it.bucket not in REVIEW_BUCKETS:
            continue
        if excluding_id is not None and it.item_id == excluding_id:
            continue
        if _series_group_key(it) == group_key:
            out.append(it)
    return out


def _maybe_cascade_ail_delete_source(
    service: MigrationReviewService,
    item: MigrationItem,
    *,
    reason: str,
) -> None:
    """Cascade pour `already_in_library` + action [d]elete source.

    Si l'item fait partie d'une série, propose de répliquer la même action
    (suppression du fichier source + persistance SKIPPED) à tous les
    épisodes de la série encore en attente. Évite à l'utilisateur de
    confirmer la suppression pour chaque épisode d'une saison déjà en DB.

    Ne s'applique qu'aux siblings en bucket ALREADY_IN_LIBRARY — les
    autres buckets (NEEDS_VALIDATION etc.) demandent une décision
    différente et restent en attente. C'est cohérent avec la sémantique :
    "ces N épisodes sont des doublons d'une version DB → supprimer toutes
    les sources".
    """
    group_key = _series_group_key(item)
    if group_key is None:
        return
    siblings = _items_in_series_group(
        service._plan, group_key, excluding_id=item.item_id
    )
    decided_ids = set(service._store.load_decisions().keys())
    # On ne cascade qu'aux siblings en ALREADY_IN_LIBRARY pour rester
    # sémantiquement cohérent avec l'action (doublon → suppression source).
    pending_siblings = [
        s for s in siblings
        if s.item_id not in decided_ids
        and s.bucket == Bucket.ALREADY_IN_LIBRARY
    ]
    if not pending_siblings:
        return
    if not Confirm.ask(
        f"[bold red]📺 Série détectée : supprimer aussi la source pour les "
        f"{len(pending_siblings)} autre(s) épisode(s) déjà en bibliothèque "
        f"?[/bold red]",
        default=True,
    ):
        return
    for sibling in pending_siblings:
        if sibling.source_path is not None and sibling.source_path.exists():
            try:
                sibling.source_path.unlink()
                console.print(
                    f"[green]✓ Supprimé :[/green] {sibling.source_path}"
                )
            except OSError as exc:
                console.print(
                    f"[red]✗ Échec suppression {sibling.source_path} : {exc}[/red]"
                )
                continue
        service.decide(
            item_id=sibling.item_id,
            decision=DecisionStatus.SKIPPED,
            reason=reason,
            decided_via="cli",
        )


def _maybe_cascade_series_decision(
    service: MigrationReviewService,
    item: MigrationItem,
    decision_status: DecisionStatus,
    *,
    reason: Optional[str] = None,
) -> None:
    """Si l'item fait partie d'une série, propose de propager une décision
    uniforme (skip/reject/web) à tous les épisodes encore en attente.

    Ne s'applique qu'aux statuts SKIPPED / REJECTED / DEFERRED_TO_WEB —
    pas aux APPROVED (qui ont des chosen_* spécifiques à l'item).
    """
    group_key = _series_group_key(item)
    if group_key is None:
        return
    siblings = _items_in_series_group(
        service._plan, group_key, excluding_id=item.item_id
    )
    # Exclut les siblings déjà décidés (en cours de session ou sessions précédentes)
    decided_ids = set(service._store.load_decisions().keys())
    pending_siblings = [s for s in siblings if s.item_id not in decided_ids]
    if len(pending_siblings) == 0:
        return
    label_map = {
        DecisionStatus.SKIPPED: "skip",
        DecisionStatus.REJECTED: "reject",
        DecisionStatus.DEFERRED_TO_WEB: "defer to web",
    }
    action_label = label_map.get(decision_status, decision_status.value)
    if not Confirm.ask(
        f"[cyan]📺 Série détectée ({len(pending_siblings)} autres épisodes en attente). "
        f"Appliquer aussi '{action_label}' à toute la série ?[/cyan]",
        default=True,
    ):
        return
    for sibling in pending_siblings:
        service.decide(
            item_id=sibling.item_id,
            decision=decision_status,
            reason=reason,
            decided_via="cli",
        )


def _handle_needs_validation(
    service: MigrationReviewService,
    item: MigrationItem,
) -> str:
    """Prompt + dispatch action pour un item needs_validation.

    Retourne 'continue' (item suivant), 'quit' (sortie loop), ou 'redraw'
    (re-affiche la même carte — typiquement après search).
    """
    candidates = item.match.top_candidates[:5]
    valid_keys = ["a", "r", "k", "q", "s", "w"]
    valid_keys.extend(str(i) for i in range(1, len(candidates) + 1))
    answer = Prompt.ask(
        "\\[a]ccept top  \\[1-N] pick  \\[s]earch  \\[r]eject  \\[k]eep skip  \\[w]eb defer  \\[q]uit",
        choices=valid_keys,
        default="k",
        show_choices=False,
    )

    if answer == "q":
        return "quit"
    if answer == "w":
        service.decide(
            item_id=item.item_id,
            decision=DecisionStatus.DEFERRED_TO_WEB,
            decided_via="cli",
        )
        _maybe_cascade_series_decision(service, item, DecisionStatus.DEFERRED_TO_WEB)
        return "continue"
    if answer == "k":
        service.decide(
            item_id=item.item_id,
            decision=DecisionStatus.SKIPPED,
            decided_via="cli",
        )
        _maybe_cascade_series_decision(service, item, DecisionStatus.SKIPPED)
        return "continue"
    if answer == "r":
        reason = Prompt.ask("Raison du rejet (optionnelle)", default="")
        service.decide(
            item_id=item.item_id,
            decision=DecisionStatus.REJECTED,
            reason=reason or None,
            decided_via="cli",
        )
        _maybe_cascade_series_decision(
            service, item, DecisionStatus.REJECTED, reason=reason or None
        )
        return "continue"
    if answer == "s":
        return _handle_search_then_pick(service, item)
    if answer == "a":
        chosen = candidates[0] if candidates else None
    else:  # "1".."5"
        chosen = candidates[int(answer) - 1]
    if chosen is None:
        console.print("[red]Pas de candidat — utilise 's'earch ou 'k'eep skip.[/red]")
        return "redraw"
    if _maybe_bulk_accept_collision(service, item, chosen):
        return "continue"
    _persist_approved(service, item, chosen)
    return "continue"


def _handle_search_then_pick(
    service: MigrationReviewService,
    item: MigrationItem,
) -> str:
    """Prompt nouveau titre, lance search TMDB, présente résultats, capture choix."""
    default_query = _default_search_query(item)
    query = Prompt.ask("Nouveau titre", default=default_query)
    if not query.strip():
        console.print("[yellow]Recherche annulée.[/yellow]")
        return "redraw"

    # Extraire une éventuelle année (4 chiffres) du query pour la passer
    # explicitement à TMDB. La double recherche côté service capture
    # quand même le cas où year n'est pas reconnu, mais passer year=
    # améliore le ranking TMDB sur les titres avec beaucoup d'homonymes.
    clean_query, year = _split_query_year(query.strip())

    is_series = _is_series_item(item)
    results = _review_run_async(
        service.search_tmdb(
            query=clean_query, is_series=is_series, year=year
        )
    )
    if not results:
        console.print(
            "[red]Aucun résultat TMDB.[/red] "
            "[dim]Astuce : essayer le titre original (souvent anglais) — "
            "TMDB indexe mal les titres traduits.[/dim]"
        )
        return "redraw"

    console.print("[bold]Résultats TMDB :[/bold]")
    for i, r in enumerate(results[:5], start=1):
        console.print(f"  {i}. {r.title:<40} ({r.year}) score {r.score:.0f}")

    pick = Prompt.ask(
        "Choisir \\[1-N] ou 'b' pour revenir",
        choices=[*[str(i) for i in range(1, min(5, len(results)) + 1)], "b"],
        default="b",
    )
    if pick == "b":
        return "redraw"

    chosen_result = results[int(pick) - 1]
    chosen = {
        "title": chosen_result.title,
        "year": chosen_result.year,
        "score": chosen_result.score,
        "tmdb_id": int(chosen_result.id) if chosen_result.id.isdigit() else None,
        "tvdb_id": None,
    }
    _persist_approved(service, item, chosen)
    return "continue"


def _handle_unrated(
    service: MigrationReviewService,
    item: MigrationItem,
) -> str:
    """Prompt + dispatch action pour un item unrated (note absente).

    Options : [m]igrate-anyway (APPROVED via match du plan), [k]eep skip,
    [q]uit.

    Retourne 'continue', 'quit'.
    """
    answer = Prompt.ask(
        "\\[m]igrate-anyway  \\[k]eep skip  \\[w]eb defer  \\[q]uit",
        choices=["m", "k", "w", "q"],
        default="k",
        show_choices=False,
    )
    if answer == "q":
        return "quit"
    if answer == "w":
        service.decide(
            item_id=item.item_id,
            decision=DecisionStatus.DEFERRED_TO_WEB,
            decided_via="cli",
        )
        _maybe_cascade_series_decision(service, item, DecisionStatus.DEFERRED_TO_WEB)
        return "continue"
    if answer == "k":
        service.decide(
            item_id=item.item_id,
            decision=DecisionStatus.SKIPPED,
            decided_via="cli",
        )
        _maybe_cascade_series_decision(service, item, DecisionStatus.SKIPPED)
        return "continue"
    # "m" → APPROVED avec le match déjà identifié au plan-time
    chosen = {
        "tmdb_id": item.match.tmdb_id,
        "tvdb_id": item.match.tvdb_id,
        "title": item.match.top_candidates[0].get("title")
        if item.match.top_candidates
        else None,
        "year": item.match.top_candidates[0].get("year")
        if item.match.top_candidates
        else None,
        "score": item.match.score,
    }
    _persist_approved(service, item, chosen)
    return "continue"


def _handle_low_rated(
    service: MigrationReviewService,
    item: MigrationItem,
) -> str:
    """Prompt + dispatch action pour un item low_rated (note sous le seuil).

    Options : [m]igrate-anyway (APPROVED), [d]elete-source-after (APPROVED +
    suppression source post-commit), [k]eep skip, [q]uit.

    Retourne 'continue', 'quit' ou 'redraw'.
    """
    answer = Prompt.ask(
        "\\[m]igrate-anyway  \\[d]elete-source-after  \\[k]eep skip  \\[w]eb defer  \\[q]uit",
        choices=["m", "d", "k", "w", "q"],
        default="k",
        show_choices=False,
    )
    if answer == "q":
        return "quit"
    if answer == "w":
        service.decide(
            item_id=item.item_id,
            decision=DecisionStatus.DEFERRED_TO_WEB,
            decided_via="cli",
        )
        _maybe_cascade_series_decision(service, item, DecisionStatus.DEFERRED_TO_WEB)
        return "continue"
    if answer == "k":
        service.decide(
            item_id=item.item_id,
            decision=DecisionStatus.SKIPPED,
            decided_via="cli",
        )
        _maybe_cascade_series_decision(service, item, DecisionStatus.SKIPPED)
        return "continue"
    delete_source = False
    if answer == "d":
        # Garde-fou : confirmation explicite avant suppression source.
        # default=True : l'utilisateur a déjà tapé 'd' (intention claire) —
        # la confirmation sert juste de double-check, un Enter suffit.
        if not Confirm.ask(
            "[red]Supprimer la source APRÈS commit transfert réussi ?[/red]",
            default=True,
        ):
            console.print("[yellow]Suppression annulée.[/yellow]")
            return "redraw"
        delete_source = True
    # Match repris du plan (identique à la logique unrated)
    top = item.match.top_candidates[0] if item.match.top_candidates else {}
    service.decide(
        item_id=item.item_id,
        decision=DecisionStatus.APPROVED,
        chosen_tmdb_id=top.get("tmdb_id") or item.match.tmdb_id,
        chosen_tvdb_id=top.get("tvdb_id") or item.match.tvdb_id,
        chosen_title=top.get("title"),
        chosen_year=top.get("year"),
        chosen_score=top.get("score") or item.match.score,
        delete_source_after=delete_source,
        decided_via="cli",
    )
    return "continue"


def _handle_already_in_library(
    service: MigrationReviewService,
    item: MigrationItem,
) -> str:
    """already_in_library : compare source NAS vs dest existante, propose action.

    Affiche la reco du DuplicateDetector (best-effort — exception capturée
    si reco indisponible), puis prompte :
      - [a]ccept reco : applique la recommandation intelligemment
      - [k]eep dest : garde la version existante, acquitte le doublon (SKIPPED)
      - [r]eplace dest : non implémenté, affiche avertissement
      - [d]elete source : supprime physiquement la source + persiste SKIPPED
      - [q]uit : sortie de la loop

    Les actions agissent immédiatement et persistent SKIPPED (jamais APPROVED)
    pour que `apply` ignore ces items sans tenter de les transférer.

    Retourne 'continue' / 'quit' / 'redraw' (cf _handle_needs_validation).
    """
    try:
        reco = service.duplicate_recommendation(item)
        reco_label = "source NAS" if reco.recommended == "new" else "dest existante"
        console.print(
            f"[bold cyan]Reco DuplicateDetector :[/bold cyan] "
            f"garder {reco_label} "
            f"(scores : new={reco.new_score:.0f} existing={reco.existing_score:.0f})"
        )
    except Exception as e:  # noqa: BLE001 — reco non bloquante
        console.print(f"[yellow]Reco indisponible : {e}[/yellow]")
        reco = None

    answer = Prompt.ask(
        "\\[a]ccept reco  \\[k]eep dest  \\[r]eplace dest  \\[d]elete source  \\[w]eb defer  \\[q]uit",
        choices=["a", "k", "r", "d", "w", "q"],
        default="k",
        show_choices=False,
    )
    if answer == "q":
        return "quit"
    if answer == "w":
        service.decide(
            item_id=item.item_id,
            decision=DecisionStatus.DEFERRED_TO_WEB,
            decided_via="cli",
        )
        _maybe_cascade_series_decision(service, item, DecisionStatus.DEFERRED_TO_WEB)
        return "continue"

    if answer == "k":
        # No-op : on garde la version DB, la source reste intacte (doublon
        # acquitté mais non supprimé). Persiste comme SKIPPED pour que
        # apply ignore l'item.
        service.decide(
            item_id=item.item_id,
            decision=DecisionStatus.SKIPPED,
            reason="doublon — version DB conservée, source laissée intacte",
            decided_via="cli",
        )
        _maybe_cascade_series_decision(
            service, item, DecisionStatus.SKIPPED,
            reason="doublon — version DB conservée, source laissée intacte",
        )
        return "continue"

    elif answer == "r":
        console.print(
            "[yellow]⚠️  [r]eplace dest n'est pas encore implémenté côté apply.[/yellow]\n"
            "    Pour remplacer manuellement : supprime la dest existante, puis\n"
            "    relance plan + review + apply sur la source seule."
        )
        return "redraw"

    elif answer == "d":
        # Affiche explicitement les 2 chemins pour lever toute ambiguïté
        existing = _existing_path_from_tag(item)
        console.print(
            f"  [yellow]À SUPPRIMER  :[/yellow] {item.source_path}\n"
            f"  [green]À CONSERVER :[/green] {existing or '(version DB déjà en place)'}"
        )
        if not Confirm.ask(
            "[bold red]Confirmer la suppression du fichier source ?[/bold red]",
            default=True,
        ):
            return "redraw"
        try:
            if item.source_path and item.source_path.exists():
                item.source_path.unlink()
                console.print(f"[green]✓ Supprimé :[/green] {item.source_path}")
            else:
                console.print(f"[yellow]Source déjà absente :[/yellow] {item.source_path}")
        except OSError as exc:
            console.print(f"[red]✗ Échec suppression : {exc}[/red]")
            return "redraw"
        service.decide(
            item_id=item.item_id,
            decision=DecisionStatus.SKIPPED,
            reason="doublon — source supprimée immédiatement",
            decided_via="cli",
        )
        _maybe_cascade_ail_delete_source(
            service, item,
            reason="doublon — source supprimée immédiatement (cascade série)",
        )
        return "continue"

    elif answer == "a":
        if reco is None:
            console.print("[red]Pas de reco — choisir manuellement.[/red]")
            return "redraw"
        if reco.recommended == "new":
            # Source meilleure → on devrait écraser dest, mais pas implémenté.
            # Suggère [r] qui guidera l'user.
            console.print(
                "[yellow]Reco suggère 'replace dest' — utilise [r] (manuel).[/yellow]"
            )
            return "redraw"
        # reco.recommended == "old" → dest meilleure → équivalent à [d]elete source
        console.print("[cyan]Reco : dest existante est meilleure — équivalent à [d]elete source.[/cyan]")
        existing = _existing_path_from_tag(item)
        console.print(
            f"  [yellow]À SUPPRIMER  :[/yellow] {item.source_path}\n"
            f"  [green]À CONSERVER :[/green] {existing or '(version DB déjà en place)'}"
        )
        if not Confirm.ask(
            "[bold red]Confirmer la suppression du fichier source ?[/bold red]",
            default=True,
        ):
            return "redraw"
        try:
            if item.source_path and item.source_path.exists():
                item.source_path.unlink()
                console.print(f"[green]✓ Supprimé :[/green] {item.source_path}")
        except OSError as exc:
            console.print(f"[red]✗ Échec suppression : {exc}[/red]")
            return "redraw"
        service.decide(
            item_id=item.item_id,
            decision=DecisionStatus.SKIPPED,
            reason="doublon — accept reco (dest meilleure) — source supprimée",
            decided_via="cli",
        )
        _maybe_cascade_ail_delete_source(
            service, item,
            reason="doublon — accept reco (cascade série)",
        )
        return "continue"

    return "redraw"  # branche inattendue, ne devrait jamais être atteinte


def _persist_approved(
    service: MigrationReviewService,
    item: MigrationItem,
    chosen: dict,
) -> None:
    """Persiste une décision APPROVED pour un item avec le candidat choisi."""
    service.decide(
        item_id=item.item_id,
        decision=DecisionStatus.APPROVED,
        chosen_tmdb_id=chosen.get("tmdb_id"),
        chosen_tvdb_id=chosen.get("tvdb_id"),
        chosen_title=chosen.get("title"),
        chosen_year=chosen.get("year"),
        chosen_score=chosen.get("score"),
        decided_via="cli",
    )


def render_review_card(
    console: Console,
    item: MigrationItem,
    *,
    position: tuple[int, int],
) -> None:
    """Affiche une carte Rich pour un item en attente.

    Format :
        ┌─ [N/total] bucket • media_root ─────────────┐
        │ Source : <path> (size MB)                    │
        │ Top candidates TMDB :                        │
        │   1. Title (year) score N                    │
        └──────────────────────────────────────────────┘
    """
    pos_n, pos_total = position
    bucket = item.bucket.value
    title_line = f"[{pos_n}/{pos_total}] {bucket} • {item.media_root or '?'}"

    size_mb = (item.size_bytes or 0) / (1024**2)
    body_lines = [
        f"[dim]Source :[/dim] {item.symlink_path}  ({size_mb:.0f} MB)",
    ]

    if item.bucket == Bucket.NEEDS_VALIDATION:
        body_lines.append("")
        body_lines.append("[bold]Top candidates TMDB :[/bold]")
        for i, c in enumerate(item.match.top_candidates[:5], start=1):
            title = c.get("title", "?")
            year = c.get("year", "?")
            score = c.get("score", 0.0)
            body_lines.append(
                f"  {i}. {title:<40} ({year}) score {score:.0f}"
            )
    elif item.bucket == Bucket.UNRATED:
        body_lines.append("[yellow]Note absente — décider de migrer.[/yellow]")
        if item.match.top_candidates:
            c = item.match.top_candidates[0]
            body_lines.append(
                f"  Match plan : {c.get('title', '?')} ({c.get('year', '?')}) "
                f"score {c.get('score', 0):.0f}"
            )
    elif item.bucket == Bucket.LOW_RATED:
        rating_value = item.rating.value
        rating_str = f"{rating_value:.1f}" if rating_value is not None else "?"
        body_lines.append(
            f"[yellow]Note {rating_str} (< seuil) — décider de migrer.[/yellow]"
        )
    elif item.bucket == Bucket.ALREADY_IN_LIBRARY:
        existing = next(
            (t.split(":", 1)[1] for t in item.tags if t.startswith("existing:")),
            "?",
        )
        body_lines.append(f"[cyan]Doublon — existe déjà :[/cyan] {existing}")

    console.print(
        Panel(
            "\n".join(body_lines),
            title=title_line,
            border_style="cyan",
        )
    )
