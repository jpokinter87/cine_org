"""
Constructeur de plan de migration NAS.

Orchestre scanner → rating_resolver → destination_planner pour produire un
MigrationPlan classifié par bucket et sérialisable en JSON. Génère également
les CSV de revue (low_rated, unrated, broken) à destination de l'utilisateur.

Aucune opération destructive : cette étape est strictement informative et
sert d'entrée au transfer_executor (étape 6).
"""

from __future__ import annotations

import asyncio
import csv
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

import xxhash

from src.core.ports.api_clients import MediaDetails
from src.services.migration._helpers import safe_int
from src.services.migration.dataclasses import (
    Bucket,
    MatchInfo,
    MigrationCandidate,
    MigrationItem,
    MigrationPlan,
    MigrationStats,
    RatingDecision,
)
from src.services.migration.destination_planner import (
    MigrationDestinationPlanner,
)
from src.services.migration.library_presence_checker import (
    LibraryPresenceChecker,
)
from src.services.migration.matching import (
    MatchKind,
    MigrationMatcher,
    candidates_to_dicts,
)
from src.services.migration.rating_resolver import MigrationRatingResolver
from src.services.migration.scanner import MigrationScanner


class _DetailsFetcher(Protocol):
    """Recupere les details d'une oeuvre TMDB ou TVDB pour son vote_average.

    Injectable pour les tests (un FakeFetcher renvoie des MediaDetails sans
    appel reseau). En production, on cable sur les clients TMDB/TVDB.
    """

    async def fetch(
        self, *, media_id: str, source: str
    ) -> Optional[MediaDetails]: ...


# Format de version courant pour le JSON sérialisé.
_PLAN_VERSION = 1


class MigrationPlanBuilder:
    """
    Orchestrateur du plan de migration.

    Mode symlinks pur (par defaut) : scanner + rating_resolver +
    destination_planner suffisent. Les fichiers physiques bruts vont en
    NOT_SYMLINK (terminal).

    Mode raw (`include_raw=True`, requiert `matcher` + `details_fetcher`) :
    pour chaque fichier physique, on identifie l'oeuvre via TMDB/TVDB, on
    fetch les details (vote_average) et on classe selon le seuil. Les
    matches ambigus / absents vont en NEEDS_VALIDATION (CSV pour
    retraitement via `process`).

    Args:
        scanner: Walker de l'arborescence source.
        rating_resolver: Résoud la note combinée d'un candidat (mode symlinks).
        destination_planner: Calcule le chemin de destination canonique.
        threshold: Note minimale (échelle 0-10) pour migrer un fichier.
            Inclusive : value >= threshold → MIGRATE.
        matcher: MigrationMatcher pour identifier les fichiers raw via API.
        details_fetcher: Fetcher de MediaDetails (vote_average) pour les
            matches confirmes en mode raw.
        include_raw: Si True, traite les fichiers `is_symlink=False` via
            matcher + fetcher au lieu de les classer en NOT_SYMLINK.
    """

    def __init__(
        self,
        scanner: MigrationScanner,
        rating_resolver: MigrationRatingResolver,
        destination_planner: MigrationDestinationPlanner,
        threshold: float = 6.0,
        *,
        matcher: Optional[MigrationMatcher] = None,
        details_fetcher: Optional[_DetailsFetcher] = None,
        include_raw: bool = False,
        library_checker: Optional[LibraryPresenceChecker] = None,
    ) -> None:
        self._scanner = scanner
        self._resolver = rating_resolver
        self._planner = destination_planner
        self._threshold = threshold
        self._matcher = matcher
        self._fetcher = details_fetcher
        self._include_raw = include_raw
        self._library_checker = library_checker

        if self._include_raw and (
            self._matcher is None or self._fetcher is None
        ):
            raise ValueError(
                "include_raw=True requires both matcher and details_fetcher"
            )

    def build(
        self,
        source_root: Path,
        destination_root: Path,
        *,
        on_progress: Optional[Callable[[MigrationItem, MigrationStats], None]] = None,
    ) -> MigrationPlan:
        """Itère sur le scanner, classe chaque candidat, et retourne le plan.

        `on_progress` (optionnel) est appelé après chaque item construit avec
        l'item et les stats courantes. Utile pour brancher une barre de
        progression Rich côté CLI.
        """
        return asyncio.run(
            self.build_async(
                source_root, destination_root, on_progress=on_progress
            )
        )

    async def build_async(
        self,
        source_root: Path,
        destination_root: Path,
        *,
        on_progress: Optional[Callable[[MigrationItem, MigrationStats], None]] = None,
    ) -> MigrationPlan:
        """Variante async (utile en mode raw où matcher/fetcher sont async)."""
        items: list[MigrationItem] = []
        stats = MigrationStats()

        for candidate in self._scanner.scan(source_root):
            stats.total_symlinks += 1

            if self._is_raw_target(candidate):
                item = await self._build_raw_item(candidate)
            else:
                item = self._build_symlink_item(candidate)

            items.append(item)
            _accumulate_stats(stats, item)

            if on_progress is not None:
                on_progress(item, stats)

        stats = _demote_movie_tmdb_collisions(items, stats)

        return MigrationPlan(
            version=_PLAN_VERSION,
            generated_at=datetime.now(timezone.utc),
            source_root=Path(source_root),
            destination_root=Path(destination_root),
            threshold=self._threshold,
            rating_strategy="max",
            stats=stats,
            items=items,
        )

    # ---- Mode symlinks (comportement legacy) ------------------------------

    def _build_symlink_item(self, candidate: MigrationCandidate) -> MigrationItem:
        decision = self._resolver.resolve(candidate)
        destination = self._planner.plan(candidate, decision)
        bucket = self._classify(candidate, decision)

        return MigrationItem(
            item_id=_compute_item_id(candidate.symlink_path),
            bucket=bucket,
            symlink_path=candidate.symlink_path,
            source_path=candidate.target_path,
            # Seul MIGRATE conserve une destination concrète. Les autres
            # buckets sont informatifs : pas de transfert prévu.
            destination_path=destination if bucket == Bucket.MIGRATE else None,
            media_root=candidate.media_root,
            relative_category=candidate.relative_category,
            size_bytes=candidate.size_bytes,
            rating=decision,
            is_symlink_source=candidate.is_symlink,
        )

    def _classify(
        self, candidate: MigrationCandidate, decision: RatingDecision
    ) -> Bucket:
        # L'ordre est volontaire : les flags techniques priment sur la note.
        if candidate.is_broken:
            return Bucket.BROKEN
        if candidate.already_on_destination:
            return Bucket.ALREADY_ON_DESTINATION
        if not candidate.is_symlink:
            return Bucket.NOT_SYMLINK
        if decision.value is None:
            return Bucket.UNRATED
        if decision.value < self._threshold:
            return Bucket.LOW_RATED
        return Bucket.MIGRATE

    # ---- Mode raw (fichiers physiques) ------------------------------------

    def _is_raw_target(self, candidate: MigrationCandidate) -> bool:
        return (
            self._include_raw
            and not candidate.is_symlink
            and self._matcher is not None
            and self._fetcher is not None
            # Les drapeaux techniques priment toujours.
            and not candidate.is_broken
            and not candidate.already_on_destination
        )

    async def _build_raw_item(
        self, candidate: MigrationCandidate
    ) -> MigrationItem:
        assert self._matcher is not None and self._fetcher is not None
        outcome = await self._matcher.match(candidate)

        top_dicts = candidates_to_dicts(outcome.top_results)

        # Court-circuit : si l'oeuvre est deja en bibliotheque CineOrg
        # (file_path non null en DB), on skip — qu'on soit MATCHED ou
        # AMBIGUOUS (tant qu'on a un top candidate avec un id parsable).
        if (
            self._library_checker is not None
            and outcome.top_results
        ):
            existing = self._library_checker.find_existing_path(
                candidate, outcome
            )
            if existing is not None:
                top = outcome.top_results[0]
                return MigrationItem(
                    item_id=_compute_item_id(candidate.symlink_path),
                    bucket=Bucket.ALREADY_IN_LIBRARY,
                    symlink_path=candidate.symlink_path,
                    source_path=candidate.target_path,
                    destination_path=None,
                    media_root=candidate.media_root,
                    relative_category=candidate.relative_category,
                    size_bytes=candidate.size_bytes,
                    rating=RatingDecision(),
                    match=_match_info_from(top, top_dicts),
                    is_symlink_source=False,
                    tags=[f"existing:{existing}"],
                )

        if outcome.kind != MatchKind.MATCHED or outcome.selected is None:
            return MigrationItem(
                item_id=_compute_item_id(candidate.symlink_path),
                bucket=Bucket.NEEDS_VALIDATION,
                symlink_path=candidate.symlink_path,
                source_path=candidate.target_path,
                destination_path=None,
                media_root=candidate.media_root,
                relative_category=candidate.relative_category,
                size_bytes=candidate.size_bytes,
                rating=RatingDecision(),
                match=MatchInfo(top_candidates=top_dicts),
                is_symlink_source=False,
            )

        selected = outcome.selected
        details = await self._fetcher.fetch(
            media_id=selected.id, source=selected.source
        )
        rating = _rating_from_details(details)
        bucket = self._classify_raw_match(rating)
        match_info = _match_info_from(selected, top_dicts)

        return MigrationItem(
            item_id=_compute_item_id(candidate.symlink_path),
            bucket=bucket,
            symlink_path=candidate.symlink_path,
            source_path=candidate.target_path,
            # En mode raw, la destination canonique nécessite la DB peuplée :
            # elle sera calculée pendant `apply` (étape 4) après l'insert
            # Movie/Series.
            destination_path=None,
            media_root=candidate.media_root,
            relative_category=candidate.relative_category,
            size_bytes=candidate.size_bytes,
            rating=rating,
            match=match_info,
            is_symlink_source=False,
        )

    def _classify_raw_match(self, rating: RatingDecision) -> Bucket:
        if rating.value is None:
            return Bucket.UNRATED
        if rating.value < self._threshold:
            return Bucket.LOW_RATED
        return Bucket.MIGRATE


def _rating_from_details(details: Optional[MediaDetails]) -> RatingDecision:
    """Construit une RatingDecision a partir du vote_average TMDB/TVDB."""
    if details is None or details.vote_average is None:
        return RatingDecision()
    return RatingDecision(
        value=float(details.vote_average),
        source="tmdb",
        tmdb=float(details.vote_average),
    )


def _match_info_from(selected, top_dicts: list[dict[str, Any]]) -> MatchInfo:
    info = MatchInfo(score=selected.score, top_candidates=top_dicts)
    media_id = safe_int(selected.id)
    if selected.source.startswith("tmdb"):
        info.tmdb_id = media_id
    elif selected.source == "tvdb":
        info.tvdb_id = media_id
    return info


def _compute_item_id(symlink_path: Path) -> str:
    """Identifiant stable d'un item, dérivé du chemin du symlink (xxh3_64)."""
    return xxhash.xxh3_64(str(symlink_path).encode("utf-8")).hexdigest()


def _accumulate_stats(stats: MigrationStats, item: MigrationItem) -> None:
    if item.bucket == Bucket.MIGRATE:
        stats.to_migrate += 1
        if item.size_bytes:
            stats.total_size_bytes += item.size_bytes
    elif item.bucket == Bucket.LOW_RATED:
        stats.low_rated += 1
    elif item.bucket == Bucket.UNRATED:
        stats.unrated += 1
    elif item.bucket == Bucket.BROKEN:
        stats.broken += 1
    elif item.bucket == Bucket.ALREADY_ON_DESTINATION:
        stats.already_on_destination += 1
    elif item.bucket == Bucket.NOT_SYMLINK:
        stats.not_symlink += 1
    elif item.bucket == Bucket.NON_VIDEO:
        stats.non_video += 1
    elif item.bucket == Bucket.NEEDS_VALIDATION:
        stats.needs_validation += 1
    elif item.bucket == Bucket.ALREADY_IN_LIBRARY:
        stats.already_in_library += 1


def _demote_movie_tmdb_collisions(
    items: list[MigrationItem], stats: MigrationStats
) -> MigrationStats:
    """Bascule en NEEDS_VALIDATION les items MIGRATE raw-film qui partagent
    leur tmdb_id avec un autre item MIGRATE, puis recalcule les stats.

    Cas typique : multi-parts (4 fichiers source → même tmdb_id → même
    destination canonique). Sans cette détection, raw_finalizer génère le
    même filename pour les N items et rsync --inplace écrase silencieusement
    chaque commit précédent. Les épisodes de série ne sont pas concernés
    (pipeline série upsert par season+episode, pas de collision possible).

    Recalcule l'intégralité des stats post-démotion plutôt qu'un décrément
    incrémental : single source of truth, stats et items ne peuvent pas
    diverger même si un futur contributeur ajoute un autre passage.
    """
    by_tmdb: dict[int, list[MigrationItem]] = {}
    for it in items:
        if it.bucket != Bucket.MIGRATE:
            continue
        if it.is_symlink_source:
            continue  # mode symlinks pur : destination déjà décidée par planner
        tmdb_id = it.match.tmdb_id
        if tmdb_id is None or it.match.tvdb_id is not None:
            continue
        media_root = (it.media_root or "").lower()
        if media_root.startswith(("seri", "séri", "anim")):
            continue  # piped via _finalize_series, pas de collision filename
        by_tmdb.setdefault(tmdb_id, []).append(it)

    for tmdb_id, group in by_tmdb.items():
        if len(group) < 2:
            continue
        tag = f"collision_tmdb:{tmdb_id}"
        for it in group:
            it.bucket = Bucket.NEEDS_VALIDATION
            if tag not in it.tags:
                it.tags.append(tag)

    # Recompute from scratch — préserve total_symlinks (compteur en amont
    # des buckets) puis ré-accumule chaque item.
    rebuilt = MigrationStats(total_symlinks=stats.total_symlinks)
    for it in items:
        _accumulate_stats(rebuilt, it)
    return rebuilt


# ---- Sérialisation JSON ---------------------------------------------------


def serialize_plan(plan: MigrationPlan) -> str:
    """Sérialise un MigrationPlan en JSON UTF-8 indenté."""
    payload = {
        "version": plan.version,
        "generated_at": plan.generated_at.isoformat(),
        "source_root": str(plan.source_root),
        "destination_root": str(plan.destination_root),
        "threshold": plan.threshold,
        "rating_strategy": plan.rating_strategy,
        "stats": asdict(plan.stats),
        "items": [_item_to_dict(it) for it in plan.items],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def deserialize_plan(payload: str) -> MigrationPlan:
    """Désérialise un JSON produit par `serialize_plan`."""
    obj = json.loads(payload)
    return MigrationPlan(
        version=obj.get("version", _PLAN_VERSION),
        generated_at=datetime.fromisoformat(obj["generated_at"]),
        source_root=Path(obj["source_root"]),
        destination_root=Path(obj["destination_root"]),
        threshold=float(obj["threshold"]),
        rating_strategy=obj.get("rating_strategy", "max"),
        stats=MigrationStats(**obj["stats"]),
        items=[_item_from_dict(d) for d in obj.get("items", [])],
    )


def _item_to_dict(item: MigrationItem) -> dict[str, Any]:
    return {
        "item_id": item.item_id,
        "bucket": item.bucket.value,
        "symlink_path": str(item.symlink_path),
        "source_path": str(item.source_path) if item.source_path else None,
        "destination_path": (
            str(item.destination_path) if item.destination_path else None
        ),
        "media_root": item.media_root,
        "relative_category": item.relative_category,
        "size_bytes": item.size_bytes,
        "rating": asdict(item.rating),
        "match": asdict(item.match),
        "is_symlink_source": item.is_symlink_source,
        "tags": list(item.tags),
    }


def _item_from_dict(d: dict[str, Any]) -> MigrationItem:
    rating = RatingDecision(**d.get("rating", {}))
    match_payload = d.get("match") or {}
    match = MatchInfo(
        tmdb_id=match_payload.get("tmdb_id"),
        tvdb_id=match_payload.get("tvdb_id"),
        score=match_payload.get("score"),
        top_candidates=list(match_payload.get("top_candidates", [])),
    )
    return MigrationItem(
        item_id=d["item_id"],
        bucket=Bucket(d["bucket"]),
        symlink_path=Path(d["symlink_path"]),
        source_path=Path(d["source_path"]) if d.get("source_path") else None,
        destination_path=(
            Path(d["destination_path"]) if d.get("destination_path") else None
        ),
        media_root=d.get("media_root", ""),
        relative_category=d.get("relative_category", ""),
        size_bytes=d.get("size_bytes"),
        rating=rating,
        match=match,
        is_symlink_source=d.get("is_symlink_source", True),
        tags=list(d.get("tags", [])),
    )


# ---- CSV de revue ---------------------------------------------------------


_CSV_FIELDS = (
    "symlink_path",
    "media_root",
    "relative_category",
    "size_bytes",
    "rating_value",
    "rating_source",
    "title_match",
    "movie_id_in_db",
    "series_id_in_db",
)


_NEEDS_VALIDATION_CSV_FIELDS = (
    "symlink_path",
    "media_root",
    "relative_category",
    "size_bytes",
    "top_candidates_json",
)


def write_review_csvs(plan: MigrationPlan, output_dir: Path) -> None:
    """
    Écrit les CSV de revue dans `output_dir`.

    - `low_rated.csv`, `unrated.csv`, `broken.csv` : items écartés du transfert.
    - `needs_validation.csv` (si mode raw activé) : matches API ambigus à
      retraiter via le workflow `process` standard.

    Chaque CSV est créé même s'il est vide (header seul) — l'absence d'un
    fichier est plus ambiguë qu'un fichier vide pour l'utilisateur.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for bucket, filename in (
        (Bucket.LOW_RATED, "low_rated.csv"),
        (Bucket.UNRATED, "unrated.csv"),
        (Bucket.BROKEN, "broken.csv"),
    ):
        rows = [it for it in plan.items if it.bucket == bucket]
        with (output_dir / filename).open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            for item in rows:
                writer.writerow(_item_to_csv_row(item))

    needs_rows = [
        it for it in plan.items if it.bucket == Bucket.NEEDS_VALIDATION
    ]
    with (output_dir / "needs_validation.csv").open(
        "w", newline="", encoding="utf-8"
    ) as f:
        writer = csv.DictWriter(f, fieldnames=_NEEDS_VALIDATION_CSV_FIELDS)
        writer.writeheader()
        for item in needs_rows:
            writer.writerow(_needs_validation_row(item))

    already_rows = [
        it for it in plan.items if it.bucket == Bucket.ALREADY_IN_LIBRARY
    ]
    with (output_dir / "already_in_library.csv").open(
        "w", newline="", encoding="utf-8"
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=(
                "source_path",
                "size_bytes",
                "tmdb_id",
                "tvdb_id",
                "existing_db_path",
            ),
        )
        writer.writeheader()
        for item in already_rows:
            existing = next(
                (t.split(":", 1)[1] for t in item.tags if t.startswith("existing:")),
                "",
            )
            writer.writerow(
                {
                    "source_path": str(item.symlink_path),
                    "size_bytes": item.size_bytes
                    if item.size_bytes is not None
                    else "",
                    "tmdb_id": item.match.tmdb_id
                    if item.match.tmdb_id is not None
                    else "",
                    "tvdb_id": item.match.tvdb_id
                    if item.match.tvdb_id is not None
                    else "",
                    "existing_db_path": existing,
                }
            )


def _item_to_csv_row(item: MigrationItem) -> dict[str, Any]:
    return {
        "symlink_path": str(item.symlink_path),
        "media_root": item.media_root,
        "relative_category": item.relative_category,
        "size_bytes": item.size_bytes if item.size_bytes is not None else "",
        "rating_value": (
            f"{item.rating.value:.2f}"
            if item.rating.value is not None
            else ""
        ),
        "rating_source": item.rating.source or "",
        "title_match": item.rating.title_match or "",
        "movie_id_in_db": (
            item.rating.movie_id_in_db
            if item.rating.movie_id_in_db is not None
            else ""
        ),
        "series_id_in_db": (
            item.rating.series_id_in_db
            if item.rating.series_id_in_db is not None
            else ""
        ),
    }


def _needs_validation_row(item: MigrationItem) -> dict[str, Any]:
    return {
        "symlink_path": str(item.symlink_path),
        "media_root": item.media_root,
        "relative_category": item.relative_category,
        "size_bytes": item.size_bytes if item.size_bytes is not None else "",
        "top_candidates_json": json.dumps(
            item.match.top_candidates, ensure_ascii=False
        ),
    }
