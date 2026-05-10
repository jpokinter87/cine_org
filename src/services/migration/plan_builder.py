"""
Constructeur de plan de migration NAS.

Orchestre scanner → rating_resolver → destination_planner pour produire un
MigrationPlan classifié par bucket et sérialisable en JSON. Génère également
les CSV de revue (low_rated, unrated, broken) à destination de l'utilisateur.

Aucune opération destructive : cette étape est strictement informative et
sert d'entrée au transfer_executor (étape 6).
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import xxhash

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
from src.services.migration.rating_resolver import MigrationRatingResolver
from src.services.migration.scanner import MigrationScanner


# Format de version courant pour le JSON sérialisé.
_PLAN_VERSION = 1


class MigrationPlanBuilder:
    """
    Orchestrateur du plan de migration.

    Args:
        scanner: Walker de l'arborescence source.
        rating_resolver: Résoud la note combinée d'un candidat.
        destination_planner: Calcule le chemin de destination canonique.
        threshold: Note minimale (échelle 0-10) pour migrer un fichier.
            Inclusive : value >= threshold → MIGRATE.
    """

    def __init__(
        self,
        scanner: MigrationScanner,
        rating_resolver: MigrationRatingResolver,
        destination_planner: MigrationDestinationPlanner,
        threshold: float = 6.0,
    ) -> None:
        self._scanner = scanner
        self._resolver = rating_resolver
        self._planner = destination_planner
        self._threshold = threshold

    def build(self, source_root: Path, destination_root: Path) -> MigrationPlan:
        """Itère sur le scanner, classe chaque candidat, et retourne le plan."""
        items: list[MigrationItem] = []
        stats = MigrationStats()

        for candidate in self._scanner.scan(source_root):
            stats.total_symlinks += 1
            decision = self._resolver.resolve(candidate)
            destination = self._planner.plan(candidate, decision)
            bucket = self._classify(candidate, decision)

            item = MigrationItem(
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
            )
            items.append(item)
            _accumulate_stats(stats, item)

        return MigrationPlan(
            version=_PLAN_VERSION,
            generated_at=datetime.utcnow(),
            source_root=Path(source_root),
            destination_root=Path(destination_root),
            threshold=self._threshold,
            rating_strategy="max",
            stats=stats,
            items=items,
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


def write_review_csvs(plan: MigrationPlan, output_dir: Path) -> None:
    """
    Écrit trois CSV (low_rated, unrated, broken) dans `output_dir`.

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


def _item_to_csv_row(item: MigrationItem) -> dict[str, Any]:
    return {
        "symlink_path": str(item.symlink_path),
        "media_root": item.media_root,
        "relative_category": item.relative_category,
        "size_bytes": item.size_bytes if item.size_bytes is not None else "",
        "rating_value": (
            item.rating.value if item.rating.value is not None else ""
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
