"""Tests pour MigrationReviewService — orchestrateur de la review."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.migration.dataclasses import (
    Bucket,
    MatchInfo,
    MigrationItem,
    MigrationPlan,
    MigrationStats,
    RatingDecision,
)
from src.services.migration.decisions import Decision, DecisionStatus
from src.services.migration.review_service import MigrationReviewService
from src.services.migration.state_store import MigrationStateStore


def _item(item_id: str, bucket: Bucket, **overrides) -> MigrationItem:
    base = dict(
        item_id=item_id,
        bucket=bucket,
        symlink_path=Path(f"/old/{item_id}.mkv"),
        source_path=Path(f"/old/{item_id}.mkv"),
        destination_path=None,
        media_root="Films",
        relative_category="",
        size_bytes=1000,
        rating=RatingDecision(),
        match=MatchInfo(),
        is_symlink_source=False,
    )
    base.update(overrides)
    return MigrationItem(**base)


def _plan(items) -> MigrationPlan:
    return MigrationPlan(
        version=1,
        source_root=Path("/src"),
        destination_root=Path("/dst"),
        threshold=6.0,
        stats=MigrationStats(),
        items=items,
    )


@pytest.fixture
def store(tmp_path):
    return MigrationStateStore(tmp_path / "s.sqlite")


def test_iter_pending_yields_review_buckets_only(store):
    plan = _plan([
        _item("m1", Bucket.MIGRATE),
        _item("nv1", Bucket.NEEDS_VALIDATION),
        _item("u1", Bucket.UNRATED),
        _item("lr1", Bucket.LOW_RATED),
        _item("ail1", Bucket.ALREADY_IN_LIBRARY),
        _item("br1", Bucket.BROKEN),
    ])
    service = MigrationReviewService(
        plan=plan,
        state_store=store,
        tmdb_client=MagicMock(),
        tvdb_client=MagicMock(),
        matcher=MagicMock(),
        duplicate_detector=MagicMock(),
    )
    pending = list(service.iter_pending())
    ids = [it.item_id for it in pending]
    assert set(ids) == {"nv1", "u1", "lr1", "ail1"}
    assert "m1" not in ids
    assert "br1" not in ids  # BROKEN exclu (sans solution review)


def test_iter_pending_filters_by_bucket(store):
    plan = _plan([
        _item("nv1", Bucket.NEEDS_VALIDATION),
        _item("u1", Bucket.UNRATED),
    ])
    service = MigrationReviewService(
        plan=plan,
        state_store=store,
        tmdb_client=MagicMock(),
        tvdb_client=MagicMock(),
        matcher=MagicMock(),
        duplicate_detector=MagicMock(),
    )
    pending = list(service.iter_pending(bucket=Bucket.NEEDS_VALIDATION))
    assert [it.item_id for it in pending] == ["nv1"]


def test_iter_pending_resume_skips_decided(store):
    plan = _plan([
        _item("nv1", Bucket.NEEDS_VALIDATION),
        _item("nv2", Bucket.NEEDS_VALIDATION),
    ])
    store.save_decision(
        Decision(
            item_id="nv1",
            bucket_origin="needs_validation",
            decision=DecisionStatus.SKIPPED,
            decided_at=datetime.now(timezone.utc),
            decided_via="cli",
        )
    )
    service = MigrationReviewService(
        plan=plan,
        state_store=store,
        tmdb_client=MagicMock(),
        tvdb_client=MagicMock(),
        matcher=MagicMock(),
        duplicate_detector=MagicMock(),
    )
    pending = list(service.iter_pending(resume=True))
    assert [it.item_id for it in pending] == ["nv2"]


def test_iter_pending_no_resume_yields_all(store):
    plan = _plan([_item("nv1", Bucket.NEEDS_VALIDATION)])
    store.save_decision(
        Decision(
            item_id="nv1",
            bucket_origin="needs_validation",
            decision=DecisionStatus.SKIPPED,
            decided_at=datetime.now(timezone.utc),
            decided_via="cli",
        )
    )
    service = MigrationReviewService(
        plan=plan,
        state_store=store,
        tmdb_client=MagicMock(),
        tvdb_client=MagicMock(),
        matcher=MagicMock(),
        duplicate_detector=MagicMock(),
    )
    pending = list(service.iter_pending(resume=False))
    assert [it.item_id for it in pending] == ["nv1"]


def test_decide_persists_via_state_store(store):
    plan = _plan([_item("nv1", Bucket.NEEDS_VALIDATION)])
    service = MigrationReviewService(
        plan=plan, state_store=store,
        tmdb_client=MagicMock(), tvdb_client=MagicMock(),
        matcher=MagicMock(), duplicate_detector=MagicMock(),
    )
    service.decide(
        item_id="nv1",
        decision=DecisionStatus.APPROVED,
        chosen_tmdb_id=19995,
        chosen_title="Avatar",
        chosen_year=2009,
        chosen_score=95.0,
        decided_via="cli",
    )
    loaded = store.get_decision("nv1")
    assert loaded.chosen_tmdb_id == 19995
    assert loaded.bucket_origin == "needs_validation"  # auto-rempli depuis l'item


def test_decide_unknown_item_id_raises(store):
    plan = _plan([_item("nv1", Bucket.NEEDS_VALIDATION)])
    service = MigrationReviewService(
        plan=plan, state_store=store,
        tmdb_client=MagicMock(), tvdb_client=MagicMock(),
        matcher=MagicMock(), duplicate_detector=MagicMock(),
    )
    with pytest.raises(KeyError, match="unknown"):
        service.decide(
            item_id="unknown",
            decision=DecisionStatus.SKIPPED,
            decided_via="cli",
        )


def test_summary_combines_pending_and_decided(store):
    plan = _plan([
        _item("nv1", Bucket.NEEDS_VALIDATION),
        _item("nv2", Bucket.NEEDS_VALIDATION),
        _item("u1", Bucket.UNRATED),
    ])
    service = MigrationReviewService(
        plan=plan, state_store=store,
        tmdb_client=MagicMock(), tvdb_client=MagicMock(),
        matcher=MagicMock(), duplicate_detector=MagicMock(),
    )
    service.decide(
        item_id="nv1",
        decision=DecisionStatus.APPROVED,
        chosen_tmdb_id=1,
        decided_via="cli",
    )
    summary = service.summary()
    assert summary["pending"] == 2
    assert summary["approved"] == 1
    assert summary["total_review_buckets"] == 3


def test_search_tmdb_movies_uses_tmdb_client_and_matcher(store):
    from src.core.ports.api_clients import SearchResult

    plan = _plan([])
    fake_tmdb = MagicMock()
    raw_results = [
        SearchResult(id="1", title="Foo", year=2020, score=0, source="tmdb"),
        SearchResult(id="2", title="Bar", year=2021, score=0, source="tmdb"),
    ]
    # tmdb_client.search est async — utilise AsyncMock
    fake_tmdb.search = AsyncMock(return_value=raw_results)
    fake_matcher = MagicMock()
    scored = [
        SearchResult(id="1", title="Foo", year=2020, score=92.0, source="tmdb"),
        SearchResult(id="2", title="Bar", year=2021, score=58.0, source="tmdb"),
    ]
    fake_matcher.score_results = MagicMock(return_value=scored)

    service = MigrationReviewService(
        plan=plan, state_store=store,
        tmdb_client=fake_tmdb, tvdb_client=MagicMock(),
        matcher=fake_matcher, duplicate_detector=MagicMock(),
    )
    results = asyncio.run(
        service.search_tmdb(query="Foo", is_series=False, year=None)
    )
    assert len(results) == 2
    assert results[0].score == 92.0
    fake_tmdb.search.assert_called_once_with("Foo", year=None)
    fake_matcher.score_results.assert_called_once_with(
        raw_results, query_title="Foo", query_year=None, is_series=False
    )


def test_search_tmdb_series_uses_search_tv(store):
    """Pour les séries avec year fourni, double recherche search_tv :
    `(query, year=)` puis `"{query} {year}"` — TMDB ignore le param year
    et range mieux quand l'année est dans le texte."""
    plan = _plan([])
    fake_tmdb = MagicMock()
    fake_tmdb.search_tv = AsyncMock(return_value=[])
    fake_matcher = MagicMock()
    fake_matcher.score_results = MagicMock(return_value=[])

    service = MigrationReviewService(
        plan=plan, state_store=store,
        tmdb_client=fake_tmdb, tvdb_client=MagicMock(),
        matcher=fake_matcher, duplicate_detector=MagicMock(),
    )
    asyncio.run(service.search_tmdb(query="GoT", is_series=True, year=2011))
    assert fake_tmdb.search_tv.call_count == 2
    fake_tmdb.search_tv.assert_any_call("GoT", year=2011)
    fake_tmdb.search_tv.assert_any_call("GoT 2011")


def test_search_tmdb_movie_double_search_when_year_provided(store):
    """Pour les films avec year, double recherche TMDB search + dédup par id."""
    from src.core.ports.api_clients import SearchResult

    plan = _plan([])
    fake_tmdb = MagicMock()
    # 1ère recherche : 1 résultat. 2e recherche : ajoute 1 résultat nouveau
    # + 1 doublon (même id) qui doit être ignoré.
    fake_tmdb.search = AsyncMock(side_effect=[
        [SearchResult(id="1", title="Foo", year=2020, score=0, source="tmdb")],
        [
            SearchResult(id="1", title="Foo", year=2020, score=0, source="tmdb"),
            SearchResult(id="2", title="Foo Other", year=2020, score=0, source="tmdb"),
        ],
    ])
    fake_matcher = MagicMock()
    fake_matcher.score_results = MagicMock(side_effect=lambda raw, **kw: raw)

    service = MigrationReviewService(
        plan=plan, state_store=store,
        tmdb_client=fake_tmdb, tvdb_client=MagicMock(),
        matcher=fake_matcher, duplicate_detector=MagicMock(),
    )
    results = asyncio.run(
        service.search_tmdb(query="Foo", is_series=False, year=2020)
    )

    assert fake_tmdb.search.call_count == 2
    # Le matcher reçoit la fusion dédupliquée : 2 éléments uniques
    raw_passed = fake_matcher.score_results.call_args.args[0]
    assert len(raw_passed) == 2
    assert [r.id for r in raw_passed] == ["1", "2"]
    assert len(results) == 2


def test_search_tmdb_fallback_imdb_when_tmdb_empty(store):
    """Quand TMDB rend 0, on cherche dans le dataset IMDb local (title.akas)
    → tconst → tmdb.find_by_imdb_id → SearchResult. Couvre les titres fr
    absents de l'index TMDB search (cas réel: 'La Maîtresse du lieutenant
    français' 1981)."""
    from src.core.ports.api_clients import MediaDetails

    plan = _plan([])
    fake_tmdb = MagicMock()
    # TMDB search rend toujours [] (les 2 appels avec year)
    fake_tmdb.search = AsyncMock(return_value=[])
    fake_tmdb.find_by_imdb_id = AsyncMock(
        return_value=MediaDetails(
            id="12537",
            title="La maîtresse du lieutenant français",
            original_title="The French Lieutenant's Woman",
            year=1981,
            vote_average=7.0,
            is_tv=False,
        )
    )
    fake_searcher = MagicMock()
    fake_searcher.search_akas = MagicMock(return_value=["tt0082416"])
    fake_matcher = MagicMock()
    fake_matcher.score_results = MagicMock(side_effect=lambda raw, **kw: raw)

    service = MigrationReviewService(
        plan=plan, state_store=store,
        tmdb_client=fake_tmdb, tvdb_client=MagicMock(),
        matcher=fake_matcher, duplicate_detector=MagicMock(),
        imdb_aka_searcher=fake_searcher,
    )
    results = asyncio.run(
        service.search_tmdb(
            query="La maitresse du lieutenant francais",
            is_series=False,
            year=1981,
        )
    )

    # TMDB a été essayé 2x (la double recherche year), puis fallback IMDb
    assert fake_tmdb.search.call_count == 2
    fake_searcher.search_akas.assert_called_once()
    fake_tmdb.find_by_imdb_id.assert_awaited_once_with("tt0082416")
    assert len(results) == 1
    assert results[0].id == "12537"
    assert results[0].source == "tmdb"


def test_search_tmdb_fallback_skipped_when_tmdb_has_results(store):
    """Si TMDB rend déjà des résultats, on n'appelle pas le fallback IMDb."""
    from src.core.ports.api_clients import SearchResult

    plan = _plan([])
    fake_tmdb = MagicMock()
    fake_tmdb.search = AsyncMock(return_value=[
        SearchResult(id="1", title="Foo", year=2020, score=0, source="tmdb"),
    ])
    fake_searcher = MagicMock()
    fake_searcher.search_akas = MagicMock()
    fake_matcher = MagicMock()
    fake_matcher.score_results = MagicMock(side_effect=lambda raw, **kw: raw)

    service = MigrationReviewService(
        plan=plan, state_store=store,
        tmdb_client=fake_tmdb, tvdb_client=MagicMock(),
        matcher=fake_matcher, duplicate_detector=MagicMock(),
        imdb_aka_searcher=fake_searcher,
    )
    asyncio.run(service.search_tmdb(query="Foo", is_series=False, year=None))

    fake_searcher.search_akas.assert_not_called()


def test_search_tmdb_no_fallback_when_searcher_is_none(store):
    """Sans imdb_aka_searcher, on garde le comportement legacy (0 résultats)."""
    plan = _plan([])
    fake_tmdb = MagicMock()
    fake_tmdb.search = AsyncMock(return_value=[])
    fake_tmdb.find_by_imdb_id = AsyncMock()
    fake_matcher = MagicMock()
    fake_matcher.score_results = MagicMock(return_value=[])

    service = MigrationReviewService(
        plan=plan, state_store=store,
        tmdb_client=fake_tmdb, tvdb_client=MagicMock(),
        matcher=fake_matcher, duplicate_detector=MagicMock(),
        imdb_aka_searcher=None,
    )
    asyncio.run(service.search_tmdb(query="Foo", is_series=False, year=None))

    fake_tmdb.find_by_imdb_id.assert_not_called()


def test_search_tmdb_movie_no_extra_call_when_year_missing(store):
    """Sans year, pas de 2e recherche (économie d'API)."""
    plan = _plan([])
    fake_tmdb = MagicMock()
    fake_tmdb.search = AsyncMock(return_value=[])
    fake_matcher = MagicMock()
    fake_matcher.score_results = MagicMock(return_value=[])

    service = MigrationReviewService(
        plan=plan, state_store=store,
        tmdb_client=fake_tmdb, tvdb_client=MagicMock(),
        matcher=fake_matcher, duplicate_detector=MagicMock(),
    )
    asyncio.run(service.search_tmdb(query="Foo", is_series=False, year=None))
    fake_tmdb.search.assert_called_once_with("Foo", year=None)


def test_duplicate_recommendation_uses_compare_quality(store, tmp_path):
    """already_in_library : compare source NAS vs file en DB via DuplicateDetector."""
    from src.services.duplicate_detector import QualityComparison

    # Création de 2 fichiers réels (le service ouvre les paths pour mediainfo)
    src = tmp_path / "source.mkv"
    src.write_bytes(b"\x00" * 1024)
    dst = tmp_path / "dest.mkv"
    dst.write_bytes(b"\x00" * 2048)

    item = _item("ail-1", Bucket.ALREADY_IN_LIBRARY,
                 source_path=src,
                 tags=[f"existing:{dst}"])
    plan = _plan([item])

    fake_dd = MagicMock()
    fake_dd.compare_quality = MagicMock(
        return_value=QualityComparison(
            recommended="new",
            existing_score=80.0,
            new_score=92.0,
            existing_breakdown={},
            new_breakdown={},
        )
    )

    service = MigrationReviewService(
        plan=plan, state_store=store,
        tmdb_client=MagicMock(), tvdb_client=MagicMock(),
        matcher=MagicMock(), duplicate_detector=fake_dd,
    )
    reco = service.duplicate_recommendation(item)
    assert reco.recommended == "new"  # source NAS gagne
    assert fake_dd.compare_quality.called
    # Vérifie que les ExistingFileInfo passés ont les bons chemins
    call_args = fake_dd.compare_quality.call_args
    existing_files, new_file = call_args.args
    assert new_file.path == src
    assert existing_files[0].path == dst
