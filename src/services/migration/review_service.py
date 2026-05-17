"""
MigrationReviewService — orchestrateur de la review interactive.

Service partagé entre CLI (`migrate-nas review`) et web
(`/migration/<plan>/review`). Encapsule :
- l'itération sur les items en attente (filtrée par bucket, resume)
- l'enregistrement des décisions (delegate à MigrationStateStore)
- la recherche TMDB live (réutilise tmdb_client + MatcherService)
- la recommandation duplicate (réutilise DuplicateDetector)

Ne touche pas au plan.json (artefact immuable). Toutes les mutations
passent par la table migration_decisions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterator, Optional

if TYPE_CHECKING:
    from src.core.ports.api_clients import SearchResult

from src.services.migration.dataclasses import (
    Bucket,
    MigrationItem,
    MigrationPlan,
)
from src.services.migration.state_store import MigrationStateStore


def _merge_unique(base: list, extra: list) -> None:
    """Étend `base` in-place avec les éléments de `extra` dont l'id n'y est pas."""
    seen = {r.id for r in base}
    for r in extra:
        if r.id not in seen:
            base.append(r)
            seen.add(r.id)


# Buckets éligibles à la review (BROKEN exclu — pas de solution UI possible).
REVIEW_BUCKETS: frozenset[Bucket] = frozenset({
    Bucket.NEEDS_VALIDATION,
    Bucket.UNRATED,
    Bucket.LOW_RATED,
    Bucket.ALREADY_IN_LIBRARY,
})


def _build_existing_file_info(path):
    """Construit un ExistingFileInfo minimaliste pour compare_quality.

    Réutilise pymediainfo via le pattern existant (cf duplicate_detector).
    Si mediainfo échoue, retourne un info avec juste path + size.
    """
    from src.services.duplicate_detector import ExistingFileInfo

    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    info = ExistingFileInfo(
        path=path,
        size_bytes=size,
        resolution=None,
        video_codec=None,
        audio_codec=None,
        video_bitrate_kbps=None,
        audio_bitrate_kbps=None,
        duration_seconds=None,
    )
    # Best-effort enrichment via mediainfo (optionnel — compare_quality
    # tolère les champs None et tombe sur la taille comme proxy).
    try:
        from pymediainfo import MediaInfo

        mi = MediaInfo.parse(str(path))
        for track in mi.tracks:
            if track.track_type == "Video" and info.resolution is None:
                if track.height:
                    info.resolution = f"{track.height}p"
                info.video_codec = track.codec_id or track.format
                if track.bit_rate:
                    info.video_bitrate_kbps = int(track.bit_rate) // 1000
                if track.duration:
                    info.duration_seconds = int(track.duration) // 1000
            if track.track_type == "Audio" and info.audio_codec is None:
                info.audio_codec = track.codec_id or track.format
                if track.bit_rate:
                    info.audio_bitrate_kbps = int(track.bit_rate) // 1000
    except Exception:  # noqa: BLE001 — mediainfo optionnel, fallback taille
        pass
    return info


class MigrationReviewService:
    """Service métier de la review interactive (4 buckets non-MIGRATE).

    Le `imdb_aka_searcher` (optionnel) est utilisé comme **fallback** par
    `search_tmdb` quand TMDB ne reconnaît pas un titre traduit (cf.
    "La Maîtresse du lieutenant français" 1981 — titre fr absent de
    l'index TMDB search). Il fournit `search_akas(query) -> list[tconst]`,
    typiquement un IMDbDatasetImporter alimenté par title.akas.tsv.gz.
    Quand None, le fallback est désactivé (comportement legacy).
    """

    def __init__(
        self,
        *,
        plan: MigrationPlan,
        state_store: MigrationStateStore,
        tmdb_client,
        tvdb_client,
        matcher,
        duplicate_detector,
        imdb_aka_searcher=None,
    ) -> None:
        self._plan = plan
        self._store = state_store
        self._tmdb = tmdb_client
        self._tvdb = tvdb_client
        self._matcher = matcher
        self._duplicate_detector = duplicate_detector
        self._imdb_aka_searcher = imdb_aka_searcher

    def iter_pending(
        self,
        *,
        bucket: Optional[Bucket] = None,
        resume: bool = True,
    ) -> Iterator[MigrationItem]:
        """Yield les items en attente de décision.

        - Filtre sur `REVIEW_BUCKETS` (exclut MIGRATE, BROKEN, etc.).
        - Si `bucket` fourni, restreint à ce bucket.
        - Si `resume=True`, skippe les items avec décision déjà persistée.
        """
        decided_ids = (
            set(self._store.load_decisions().keys()) if resume else set()
        )
        for item in self._plan.items:
            if item.bucket not in REVIEW_BUCKETS:
                continue
            if bucket is not None and item.bucket != bucket:
                continue
            if item.item_id in decided_ids:
                continue
            yield item

    def decide(
        self,
        *,
        item_id: str,
        decision,  # DecisionStatus
        decided_via: str,
        chosen_tmdb_id: Optional[int] = None,
        chosen_tvdb_id: Optional[int] = None,
        chosen_title: Optional[str] = None,
        chosen_year: Optional[int] = None,
        chosen_score: Optional[float] = None,
        duplicate_action=None,  # DuplicateAction
        delete_source_after: bool = False,
        reason: Optional[str] = None,
    ) -> None:
        """Persiste une décision sur un item du plan.

        Auto-rempli `bucket_origin` depuis le bucket actuel de l'item
        (informationnel pour audit). Idempotent.
        """
        from datetime import datetime, timezone

        from src.services.migration.decisions import Decision

        item = self._find_item(item_id)
        self._store.save_decision(
            Decision(
                item_id=item_id,
                bucket_origin=item.bucket.value,
                decision=decision,
                chosen_tmdb_id=chosen_tmdb_id,
                chosen_tvdb_id=chosen_tvdb_id,
                chosen_title=chosen_title,
                chosen_year=chosen_year,
                chosen_score=chosen_score,
                duplicate_action=duplicate_action,
                delete_source_after=delete_source_after,
                reason=reason,
                decided_at=datetime.now(timezone.utc),
                decided_via=decided_via,
            )
        )

    def summary(self) -> dict[str, int]:
        """Retourne le récap : pending vs décidés (par status).

        Filtre les décisions sur les item_ids du plan actuel — le state store
        peut contenir des décisions résiduelles d'anciens plans ayant utilisé
        le même `<plan>.state.sqlite` (path par convention). Sans ce filtre,
        les compteurs s'agrègent à travers les générations de plans et
        l'utilisateur voit des totaux incompréhensibles (ex : 193 décisions
        sur un plan de 15 items).
        """
        from src.services.migration.decisions import DecisionStatus

        review_items = [
            it for it in self._plan.items if it.bucket in REVIEW_BUCKETS
        ]
        review_ids = {it.item_id for it in review_items}
        all_decisions = self._store.load_decisions()
        plan_decisions = [
            d for item_id, d in all_decisions.items() if item_id in review_ids
        ]
        pending = sum(
            1 for it in review_items if it.item_id not in all_decisions
        )
        out: dict[str, int] = {
            "total_review_buckets": len(review_items),
            "pending": pending,
        }
        for status in DecisionStatus:
            out[status.value] = sum(
                1 for d in plan_decisions if d.decision == status
            )
        return out

    async def search_tmdb(
        self,
        *,
        query: str,
        is_series: bool,
        year: Optional[int] = None,
    ) -> list["SearchResult"]:
        """Recherche TMDB live + scoring. Retourne list[SearchResult] scorée.

        Aligné sur le matcher migration : double recherche TMDB
        (`search(query, year)` + `search(f"{query} {year}")`) quand year
        est fourni — TMDB ignore le param year et range mieux quand
        l'année est dans le texte. Dédup par id.

        Pour les séries : `tmdb.search_tv` (idem double appel si year fourni).
        Pas de fallback TVDB ici — l'utilisateur peut chercher par ID
        externe via `validation_service.search_by_external_id` si besoin.

        Fallback IMDb : si TMDB rend 0 résultat ET qu'un `imdb_aka_searcher`
        est branché, on cherche le titre dans le dataset local `title.akas`
        → tconst → `tmdb.find_by_imdb_id(tconst)`. Couvre les titres
        traduits absents de l'index TMDB search (ex: titres fr de films
        anglo-saxons publiés avant les années 2000).
        """
        if is_series:
            raw = await self._tmdb.search_tv(query, year=year)
            if year is not None:
                extra = await self._tmdb.search_tv(f"{query} {year}")
                _merge_unique(raw, extra)
        else:
            raw = await self._tmdb.search(query, year=year)
            if year is not None:
                extra = await self._tmdb.search(f"{query} {year}")
                _merge_unique(raw, extra)

        if not raw and self._imdb_aka_searcher is not None:
            raw = await self._fallback_imdb_lookup(query)

        return self._matcher.score_results(
            raw, query_title=query, query_year=year, is_series=is_series
        )

    async def _fallback_imdb_lookup(self, query: str) -> list["SearchResult"]:
        """Cherche `query` dans `title.akas` local → tconst → TMDB find.

        Retourne une liste de SearchResult construits depuis MediaDetails
        TMDB (champs : id, title, original_title, year). Le scoring est
        fait en amont par l'appelant. Limite à 5 candidats pour éviter
        une rafale d'appels TMDB sur les titres très ambigus.
        """
        from src.core.ports.api_clients import SearchResult

        tconsts = self._imdb_aka_searcher.search_akas(query, limit=5)
        if not tconsts:
            return []

        results: list[SearchResult] = []
        for tconst in tconsts:
            try:
                details = await self._tmdb.find_by_imdb_id(tconst)
            except Exception:  # noqa: BLE001 — best-effort fallback
                continue
            if details is None:
                continue
            results.append(
                SearchResult(
                    id=details.id,
                    title=details.title,
                    original_title=details.original_title,
                    year=details.year,
                    source="tmdb_tv" if details.is_tv else "tmdb",
                )
            )
        return results

    def duplicate_recommendation(self, item: MigrationItem):
        """Pour un item already_in_library : score qualité source vs dest.

        Lit le tag `existing:<path>` posé par le plan_builder. Délègue le
        scoring au DuplicateDetector existant via `compare_quality`.
        Retourne un `QualityComparison` (recommended="new"|"old", scores,
        breakdowns pour affichage).
        """
        from pathlib import Path

        existing_path: Optional[Path] = None
        for tag in item.tags:
            if tag.startswith("existing:"):
                existing_path = Path(tag.split(":", 1)[1])
                break
        if existing_path is None:
            raise ValueError(
                f"item {item.item_id} sans tag 'existing:' — pas un doublon"
            )
        if item.source_path is None:
            raise ValueError(f"item {item.item_id} sans source_path")

        # Construit les ExistingFileInfo via mediainfo extraction
        # (réutilise les helpers internes — voir _build_existing_file_info).
        new_info = _build_existing_file_info(item.source_path)
        existing_info = _build_existing_file_info(existing_path)
        return self._duplicate_detector.compare_quality(
            [existing_info], new_info
        )

    def _find_item(self, item_id: str) -> MigrationItem:
        for it in self._plan.items:
            if it.item_id == item_id:
                return it
        raise KeyError(f"unknown item_id: {item_id}")
