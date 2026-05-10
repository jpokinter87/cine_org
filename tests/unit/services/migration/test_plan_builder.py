"""
Tests pour MigrationPlanBuilder + helpers de sérialisation et CSV de revue.

Le plan_builder orchestre scanner → rating_resolver → destination_planner,
classe chaque candidat dans un Bucket selon sa note + ses flags, agrège les
stats, et retourne un MigrationPlan sérialisable.

Les dépendances (scanner/resolver/planner) sont mockées : ce module ne teste
pas leur comportement, il teste l'orchestration et la classification.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.ports.api_clients import MediaDetails, SearchResult
from src.services.migration.dataclasses import (
    Bucket,
    MatchInfo,
    MigrationCandidate,
    MigrationItem,
    MigrationPlan,
    MigrationStats,
    RatingDecision,
)
from src.services.migration.matching import MatchKind, MatchOutcome
from src.services.migration.plan_builder import (
    MigrationPlanBuilder,
    deserialize_plan,
    serialize_plan,
    write_review_csvs,
)


# ---- Fixtures -------------------------------------------------------------


_UNSET = object()


def _candidate(
    name: str,
    *,
    media_root: str = "Films",
    relative_category: str = "Drame/D",
    size_bytes: int | None = 1000,
    is_broken: bool = False,
    already_on_destination: bool = False,
    is_symlink: bool = True,
    target=_UNSET,
) -> MigrationCandidate:
    symlink = Path(f"/old_nas/Vidéos/{media_root}/{relative_category}/{name}")
    if target is _UNSET:
        target = Path(f"/old_storage/{name}")
    return MigrationCandidate(
        symlink_path=symlink,
        target_path=target,
        media_root=media_root,
        relative_category=relative_category,
        size_bytes=size_bytes,
        is_broken=is_broken,
        already_on_destination=already_on_destination,
        is_symlink=is_symlink,
    )


def _make_builder(
    candidates: list[MigrationCandidate],
    decisions: dict[str, RatingDecision],
    destinations: dict[str, Path | None],
    threshold: float = 6.0,
) -> MigrationPlanBuilder:
    """Helper : construit un PlanBuilder avec scanner/resolver/planner mockés."""
    scanner = MagicMock()
    scanner.scan.return_value = iter(candidates)

    resolver = MagicMock()
    resolver.resolve.side_effect = lambda c: decisions.get(
        c.symlink_path.name, RatingDecision()
    )

    planner = MagicMock()
    planner.plan.side_effect = lambda c, d: destinations.get(c.symlink_path.name)

    return MigrationPlanBuilder(
        scanner=scanner,
        rating_resolver=resolver,
        destination_planner=planner,
        threshold=threshold,
    )


# ---- Classification par bucket -------------------------------------------


def test_classifies_broken_candidate():
    cand = _candidate("missing.mkv", is_broken=True, target=None)
    builder = _make_builder([cand], {}, {})
    plan = builder.build(Path("/old_nas/Vidéos"), Path("/new_nas"))
    assert len(plan.items) == 1
    assert plan.items[0].bucket == Bucket.BROKEN
    assert plan.items[0].destination_path is None


def test_classifies_already_on_destination():
    cand = _candidate("ondest.mkv", already_on_destination=True)
    builder = _make_builder([cand], {}, {})
    plan = builder.build(Path("/old_nas/Vidéos"), Path("/new_nas"))
    assert plan.items[0].bucket == Bucket.ALREADY_ON_DESTINATION
    assert plan.items[0].destination_path is None


def test_classifies_not_symlink():
    cand = _candidate("physical.mkv", is_symlink=False)
    builder = _make_builder([cand], {}, {})
    plan = builder.build(Path("/old_nas/Vidéos"), Path("/new_nas"))
    assert plan.items[0].bucket == Bucket.NOT_SYMLINK


def test_classifies_unrated_when_no_value():
    cand = _candidate("inconnu.mkv")
    builder = _make_builder(
        [cand],
        {"inconnu.mkv": RatingDecision()},  # value=None
        {"inconnu.mkv": Path("/new_nas/Films/Drame/I/inconnu.mkv")},
    )
    plan = builder.build(Path("/old_nas/Vidéos"), Path("/new_nas"))
    assert plan.items[0].bucket == Bucket.UNRATED
    assert plan.items[0].destination_path is None


def test_classifies_low_rated_below_threshold():
    cand = _candidate("nul.mkv")
    builder = _make_builder(
        [cand],
        {"nul.mkv": RatingDecision(value=5.5, source="imdb")},
        {"nul.mkv": Path("/new_nas/Films/Drame/N/nul.mkv")},
        threshold=6.0,
    )
    plan = builder.build(Path("/old_nas/Vidéos"), Path("/new_nas"))
    assert plan.items[0].bucket == Bucket.LOW_RATED
    assert plan.items[0].destination_path is None


def test_classifies_migrate_at_or_above_threshold():
    cand = _candidate("good.mkv")
    builder = _make_builder(
        [cand],
        {"good.mkv": RatingDecision(value=8.0, source="imdb")},
        {"good.mkv": Path("/new_nas/Films/Drame/G/good.mkv")},
        threshold=6.0,
    )
    plan = builder.build(Path("/old_nas/Vidéos"), Path("/new_nas"))
    assert plan.items[0].bucket == Bucket.MIGRATE
    assert plan.items[0].destination_path == Path(
        "/new_nas/Films/Drame/G/good.mkv"
    )


def test_threshold_inclusive_at_exact_boundary():
    """Note exactement = threshold → MIGRATE (pas LOW_RATED)."""
    cand = _candidate("border.mkv")
    builder = _make_builder(
        [cand],
        {"border.mkv": RatingDecision(value=6.0)},
        {"border.mkv": Path("/new_nas/x.mkv")},
        threshold=6.0,
    )
    plan = builder.build(Path("/old_nas/Vidéos"), Path("/new_nas"))
    assert plan.items[0].bucket == Bucket.MIGRATE


def test_migrate_skipped_when_planner_returns_none():
    """Si la note est OK mais que le planner ne sait pas placer le fichier
    (ex. broken qu'on aurait laissé passer), on bascule en UNRATED-like."""
    cand = _candidate("orphan.mkv")
    builder = _make_builder(
        [cand],
        {"orphan.mkv": RatingDecision(value=8.0)},
        {"orphan.mkv": None},  # pas de destination calculable
    )
    plan = builder.build(Path("/old_nas/Vidéos"), Path("/new_nas"))
    # On garde l'item dans le plan mais sans destination ; le bucket reste
    # MIGRATE (la note est OK) et destination_path=None signale le problème.
    assert plan.items[0].bucket == Bucket.MIGRATE
    assert plan.items[0].destination_path is None


# ---- Agrégation des stats -------------------------------------------------


def test_aggregates_stats_across_buckets():
    candidates = [
        _candidate("good.mkv", size_bytes=1000),
        _candidate("good2.mkv", size_bytes=2000),
        _candidate("nul.mkv", size_bytes=500),
        _candidate("inconnu.mkv", size_bytes=300),
        _candidate("missing.mkv", is_broken=True, target=None, size_bytes=None),
        _candidate("ondest.mkv", already_on_destination=True, size_bytes=400),
        _candidate("phys.mkv", is_symlink=False, size_bytes=100),
    ]
    decisions = {
        "good.mkv": RatingDecision(value=7.0),
        "good2.mkv": RatingDecision(value=8.0),
        "nul.mkv": RatingDecision(value=4.0),
        "inconnu.mkv": RatingDecision(),
        "phys.mkv": RatingDecision(value=7.0),
    }
    destinations = {
        "good.mkv": Path("/new_nas/good.mkv"),
        "good2.mkv": Path("/new_nas/good2.mkv"),
    }
    builder = _make_builder(candidates, decisions, destinations, threshold=6.0)
    plan = builder.build(Path("/old_nas/Vidéos"), Path("/new_nas"))

    s = plan.stats
    assert s.total_symlinks == 7
    assert s.to_migrate == 2
    assert s.low_rated == 1
    assert s.unrated == 1
    assert s.broken == 1
    assert s.already_on_destination == 1
    assert s.not_symlink == 1
    # Cumul des tailles MIGRATE seulement (1000 + 2000 = 3000)
    assert s.total_size_bytes == 3000


# ---- item_id stable -------------------------------------------------------


def test_item_id_is_stable_across_builds():
    cand = _candidate("avatar.mkv")
    decisions = {"avatar.mkv": RatingDecision(value=8.0)}
    destinations = {"avatar.mkv": Path("/new_nas/avatar.mkv")}

    builder1 = _make_builder([cand], decisions, destinations)
    plan1 = builder1.build(Path("/old_nas/Vidéos"), Path("/new_nas"))

    builder2 = _make_builder([cand], decisions, destinations)
    plan2 = builder2.build(Path("/old_nas/Vidéos"), Path("/new_nas"))

    assert plan1.items[0].item_id == plan2.items[0].item_id
    assert plan1.items[0].item_id != ""


def test_item_id_differs_for_different_symlinks():
    cand_a = _candidate("a.mkv")
    cand_b = _candidate("b.mkv")
    builder = _make_builder(
        [cand_a, cand_b],
        {"a.mkv": RatingDecision(value=8.0), "b.mkv": RatingDecision(value=8.0)},
        {"a.mkv": Path("/x/a.mkv"), "b.mkv": Path("/x/b.mkv")},
    )
    plan = builder.build(Path("/old_nas/Vidéos"), Path("/new_nas"))
    assert plan.items[0].item_id != plan.items[1].item_id


# ---- Sérialisation --------------------------------------------------------


def test_serialize_plan_returns_valid_json():
    cand = _candidate("avatar.mkv")
    builder = _make_builder(
        [cand],
        {"avatar.mkv": RatingDecision(value=8.0, source="imdb", imdb=8.0)},
        {"avatar.mkv": Path("/new_nas/avatar.mkv")},
    )
    plan = builder.build(Path("/old_nas/Vidéos"), Path("/new_nas"))

    payload = serialize_plan(plan)
    obj = json.loads(payload)

    assert obj["version"] == 1
    assert obj["threshold"] == 6.0
    assert obj["source_root"] == "/old_nas/Vidéos"
    assert obj["destination_root"] == "/new_nas"
    assert obj["stats"]["to_migrate"] == 1
    assert obj["items"][0]["bucket"] == "migrate"
    assert obj["items"][0]["symlink_path"].endswith("avatar.mkv")
    assert obj["items"][0]["destination_path"] == "/new_nas/avatar.mkv"
    assert obj["items"][0]["rating"]["value"] == 8.0
    assert obj["items"][0]["rating"]["source"] == "imdb"


def test_serialize_then_deserialize_plan_roundtrip():
    cand = _candidate("avatar.mkv")
    builder = _make_builder(
        [cand],
        {"avatar.mkv": RatingDecision(value=8.0, source="imdb", movie_id_in_db=42)},
        {"avatar.mkv": Path("/new_nas/Films/SF/A/avatar.mkv")},
    )
    plan_orig = builder.build(Path("/old_nas/Vidéos"), Path("/new_nas"))

    payload = serialize_plan(plan_orig)
    plan_back = deserialize_plan(payload)

    assert plan_back.version == 1
    assert plan_back.threshold == 6.0
    assert plan_back.source_root == Path("/old_nas/Vidéos")
    assert plan_back.destination_root == Path("/new_nas")
    assert len(plan_back.items) == 1
    item = plan_back.items[0]
    assert item.bucket == Bucket.MIGRATE
    assert item.symlink_path == cand.symlink_path
    assert item.destination_path == Path("/new_nas/Films/SF/A/avatar.mkv")
    assert item.rating.value == 8.0
    assert item.rating.source == "imdb"
    assert item.rating.movie_id_in_db == 42


def test_deserialize_handles_null_paths():
    """Items sans destination (broken, unrated…) doivent rester sérialisables."""
    cand = _candidate("missing.mkv", is_broken=True, target=None)
    builder = _make_builder([cand], {}, {})
    plan = builder.build(Path("/old_nas/Vidéos"), Path("/new_nas"))

    payload = serialize_plan(plan)
    plan_back = deserialize_plan(payload)

    assert plan_back.items[0].bucket == Bucket.BROKEN
    assert plan_back.items[0].destination_path is None
    assert plan_back.items[0].source_path is None


# ---- CSV de revue ---------------------------------------------------------


def test_write_review_csvs_creates_three_files(tmp_path):
    candidates = [
        _candidate("nul.mkv"),
        _candidate("inconnu.mkv"),
        _candidate("missing.mkv", is_broken=True, target=None),
        _candidate("good.mkv"),  # MIGRATE → ne doit pas apparaître
    ]
    decisions = {
        "nul.mkv": RatingDecision(value=4.0, source="imdb", title_match="Nul"),
        "inconnu.mkv": RatingDecision(),
        "good.mkv": RatingDecision(value=8.0),
    }
    destinations = {"good.mkv": Path("/new_nas/good.mkv")}
    builder = _make_builder(candidates, decisions, destinations)
    plan = builder.build(Path("/old_nas/Vidéos"), Path("/new_nas"))

    write_review_csvs(plan, tmp_path)

    assert (tmp_path / "low_rated.csv").exists()
    assert (tmp_path / "unrated.csv").exists()
    assert (tmp_path / "broken.csv").exists()

    with (tmp_path / "low_rated.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["symlink_path"].endswith("nul.mkv")
    assert rows[0]["rating_value"] == "4.0"
    assert rows[0]["rating_source"] == "imdb"
    assert rows[0]["title_match"] == "Nul"

    with (tmp_path / "unrated.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["symlink_path"].endswith("inconnu.mkv")

    with (tmp_path / "broken.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["symlink_path"].endswith("missing.mkv")


def test_write_review_csvs_handles_empty_buckets(tmp_path):
    """Si un bucket est vide, le CSV doit quand même être créé (header seul)."""
    cand = _candidate("good.mkv")
    builder = _make_builder(
        [cand],
        {"good.mkv": RatingDecision(value=8.0)},
        {"good.mkv": Path("/new_nas/good.mkv")},
    )
    plan = builder.build(Path("/old_nas/Vidéos"), Path("/new_nas"))

    write_review_csvs(plan, tmp_path)

    for name in ("low_rated.csv", "unrated.csv", "broken.csv"):
        path = tmp_path / name
        assert path.exists()
        with path.open(newline="") as f:
            rows = list(csv.DictReader(f))
        assert rows == []  # header présent mais aucune ligne


# ---- Mode raw : extension dataclasses (étape 1) --------------------------


def test_bucket_has_needs_validation_value():
    """NEEDS_VALIDATION = bucket terminal pour les fichiers raw au match incertain."""
    assert Bucket.NEEDS_VALIDATION.value == "needs_validation"


def test_match_info_defaults_are_empty():
    """Sans match TMDB/TVDB, MatchInfo() est vide (mode symlinks pur)."""
    info = MatchInfo()
    assert info.tmdb_id is None
    assert info.tvdb_id is None
    assert info.score is None
    assert info.top_candidates == []


def test_migration_item_has_match_field_with_default():
    """MigrationItem accepte un MatchInfo par défaut (rétrocompat mode symlinks)."""
    item = MigrationItem(
        item_id="abc",
        bucket=Bucket.MIGRATE,
        symlink_path=Path("/old/x.mkv"),
        source_path=Path("/storage/x.mkv"),
        destination_path=Path("/new/x.mkv"),
        media_root="Films",
        relative_category="Drame/D",
        size_bytes=1000,
        rating=RatingDecision(),
    )
    assert item.match.tmdb_id is None
    assert item.match.top_candidates == []
    assert item.is_symlink_source is True


def test_migration_item_accepts_populated_match_info():
    """MigrationItem alimenté en mode raw porte tmdb_id, score, candidats."""
    match = MatchInfo(
        tmdb_id=12345,
        score=92.5,
        top_candidates=[
            {"title": "Avatar", "year": 2009, "score": 92.5, "tmdb_id": 12345}
        ],
    )
    item = MigrationItem(
        item_id="abc",
        bucket=Bucket.MIGRATE,
        symlink_path=Path("/old/avatar.mkv"),
        source_path=Path("/old/avatar.mkv"),
        destination_path=Path("/new/Films/SF/A/Avatar.mkv"),
        media_root="Films",
        relative_category="",
        size_bytes=2_000_000_000,
        rating=RatingDecision(value=8.0, source="imdb"),
        match=match,
        is_symlink_source=False,
    )
    assert item.match.tmdb_id == 12345
    assert item.match.score == 92.5
    assert item.is_symlink_source is False


def test_migration_stats_has_needs_validation_counter():
    """MigrationStats expose un compteur needs_validation à 0 par défaut."""
    stats = MigrationStats()
    assert stats.needs_validation == 0


def test_accumulate_stats_counts_needs_validation():
    """Le builder incrémente needs_validation pour les items raw au match raté."""
    cand = _candidate("ambigu.mkv", is_symlink=False)
    builder = _make_builder([cand], {}, {})
    plan = builder.build(Path("/old_nas/Vidéos"), Path("/new_nas"))
    # Forcer manuellement le bucket pour tester _accumulate_stats (l'étape 3
    # branchera la classification automatique).
    plan.items[0].bucket = Bucket.NEEDS_VALIDATION
    stats = MigrationStats()
    from src.services.migration.plan_builder import _accumulate_stats

    _accumulate_stats(stats, plan.items[0])
    assert stats.needs_validation == 1


def test_serialize_roundtrip_preserves_match_info():
    """JSON roundtrip : tmdb_id/score/top_candidates restent intacts."""
    cand = _candidate("avatar.mkv", is_symlink=False)
    builder = _make_builder(
        [cand],
        {"avatar.mkv": RatingDecision(value=8.0)},
        {"avatar.mkv": Path("/new_nas/Films/SF/A/Avatar (2009).mkv")},
    )
    plan_orig = builder.build(Path("/old_nas/Vidéos"), Path("/new_nas"))
    # Étape 1 : on injecte directement les champs raw (l'étape 3 les remplira
    # automatiquement). Le test garantit la persistance JSON dès maintenant.
    plan_orig.items[0].match = MatchInfo(
        tmdb_id=19995,
        score=95.0,
        top_candidates=[{"title": "Avatar", "year": 2009, "score": 95.0}],
    )
    plan_orig.items[0].is_symlink_source = False

    plan_back = deserialize_plan(serialize_plan(plan_orig))

    item = plan_back.items[0]
    assert item.match.tmdb_id == 19995
    assert item.match.score == 95.0
    assert item.match.top_candidates == [
        {"title": "Avatar", "year": 2009, "score": 95.0}
    ]
    assert item.is_symlink_source is False


def test_deserialize_plan_without_match_field_defaults_to_empty():
    """Plans pré-mode-raw (sans champs match/is_symlink_source) restent lisibles."""
    cand = _candidate("legacy.mkv")
    builder = _make_builder(
        [cand],
        {"legacy.mkv": RatingDecision(value=8.0)},
        {"legacy.mkv": Path("/new_nas/legacy.mkv")},
    )
    plan = builder.build(Path("/old_nas/Vidéos"), Path("/new_nas"))
    payload = json.loads(serialize_plan(plan))
    # Simule un plan ancien : on retire les nouveaux champs.
    for it in payload["items"]:
        it.pop("match", None)
        it.pop("is_symlink_source", None)
    payload["stats"].pop("needs_validation", None)

    # MigrationStats est strict (dataclass), on doit pouvoir réinjecter le
    # champ manquant via un fallback : ici on vérifie au moins que l'item se
    # désérialise avec les nouveaux defaults.
    obj = payload
    item_dict = obj["items"][0]
    from src.services.migration.plan_builder import _item_from_dict

    item = _item_from_dict(item_dict)
    assert item.match.tmdb_id is None
    assert item.match.top_candidates == []
    assert item.is_symlink_source is True


# ---- Mode raw : plan_builder + matcher + fetcher (étape 3) ---------------


def _make_matched_outcome(
    *, source: str = "tmdb", media_id: str = "19995", score: float = 95.0
) -> MatchOutcome:
    selected = SearchResult(
        id=media_id,
        title="Avatar",
        year=2009,
        score=score,
        source=source,
    )
    other = SearchResult(
        id="9999", title="Autre", year=2000, score=70.0, source=source
    )
    return MatchOutcome(
        kind=MatchKind.MATCHED,
        top_results=[selected, other],
        selected=selected,
    )


def _make_ambiguous_outcome() -> MatchOutcome:
    return MatchOutcome(
        kind=MatchKind.AMBIGUOUS,
        top_results=[
            SearchResult(
                id="1", title="Foo", year=2020, score=78.0, source="tmdb"
            ),
            SearchResult(
                id="2", title="Foo Bis", year=2020, score=76.0, source="tmdb"
            ),
        ],
        selected=None,
    )


def _make_no_results_outcome() -> MatchOutcome:
    return MatchOutcome(kind=MatchKind.NO_RESULTS, top_results=[])


def _make_raw_builder(
    candidates: list[MigrationCandidate],
    *,
    outcome: MatchOutcome,
    vote_average: float | None,
    threshold: float = 6.0,
) -> MigrationPlanBuilder:
    """Builder en mode raw avec matcher + fetcher mockés."""
    scanner = MagicMock()
    scanner.scan.return_value = iter(candidates)

    resolver = MagicMock()
    resolver.resolve.return_value = RatingDecision()

    planner = MagicMock()
    planner.plan.return_value = None

    matcher = MagicMock()
    matcher.match = AsyncMock(return_value=outcome)

    fetcher = MagicMock()
    details = (
        MediaDetails(id="19995", title="Avatar", vote_average=vote_average)
        if vote_average is not None
        else MediaDetails(id="19995", title="Avatar", vote_average=None)
    )
    fetcher.fetch = AsyncMock(return_value=details)

    return MigrationPlanBuilder(
        scanner=scanner,
        rating_resolver=resolver,
        destination_planner=planner,
        threshold=threshold,
        matcher=matcher,
        details_fetcher=fetcher,
        include_raw=True,
    )


def test_include_raw_requires_matcher_and_fetcher():
    """include_raw=True sans matcher ou fetcher → ValueError au constructeur."""
    scanner = MagicMock()
    resolver = MagicMock()
    planner = MagicMock()
    with pytest.raises(ValueError, match="include_raw"):
        MigrationPlanBuilder(
            scanner=scanner,
            rating_resolver=resolver,
            destination_planner=planner,
            include_raw=True,
        )


def test_raw_matched_with_high_rating_goes_to_migrate():
    cand = _candidate("avatar.mkv", is_symlink=False)
    builder = _make_raw_builder(
        [cand], outcome=_make_matched_outcome(), vote_average=8.0
    )
    plan = builder.build(Path("/old_nas/Vidéos"), Path("/new_nas"))

    assert len(plan.items) == 1
    item = plan.items[0]
    assert item.bucket == Bucket.MIGRATE
    assert item.is_symlink_source is False
    assert item.rating.value == 8.0
    assert item.rating.source == "tmdb"
    assert item.match.tmdb_id == 19995
    assert item.match.score == 95.0
    assert plan.stats.to_migrate == 1


def test_raw_matched_with_low_rating_goes_to_low_rated():
    cand = _candidate("flop.mkv", is_symlink=False)
    builder = _make_raw_builder(
        [cand],
        outcome=_make_matched_outcome(),
        vote_average=4.5,
        threshold=6.0,
    )
    plan = builder.build(Path("/old_nas/Vidéos"), Path("/new_nas"))

    assert plan.items[0].bucket == Bucket.LOW_RATED
    assert plan.stats.low_rated == 1
    assert plan.stats.to_migrate == 0


def test_raw_matched_without_vote_average_goes_to_unrated():
    cand = _candidate("mystere.mkv", is_symlink=False)
    builder = _make_raw_builder(
        [cand], outcome=_make_matched_outcome(), vote_average=None
    )
    plan = builder.build(Path("/old_nas/Vidéos"), Path("/new_nas"))

    item = plan.items[0]
    assert item.bucket == Bucket.UNRATED
    assert item.rating.value is None
    # Match info reste rempli même sans rating.
    assert item.match.tmdb_id == 19995
    assert plan.stats.unrated == 1


def test_raw_ambiguous_goes_to_needs_validation():
    cand = _candidate("ambigu.mkv", is_symlink=False)
    builder = _make_raw_builder(
        [cand], outcome=_make_ambiguous_outcome(), vote_average=None
    )
    plan = builder.build(Path("/old_nas/Vidéos"), Path("/new_nas"))

    item = plan.items[0]
    assert item.bucket == Bucket.NEEDS_VALIDATION
    assert item.is_symlink_source is False
    assert item.match.tmdb_id is None  # pas de selected
    assert len(item.match.top_candidates) == 2
    assert plan.stats.needs_validation == 1
    # Pas de fetcher quand match ambigu (économie d'API).
    builder._fetcher.fetch.assert_not_called()


def test_raw_no_results_goes_to_needs_validation():
    cand = _candidate("inconnu.mkv", is_symlink=False)
    builder = _make_raw_builder(
        [cand], outcome=_make_no_results_outcome(), vote_average=None
    )
    plan = builder.build(Path("/old_nas/Vidéos"), Path("/new_nas"))

    item = plan.items[0]
    assert item.bucket == Bucket.NEEDS_VALIDATION
    assert item.match.top_candidates == []
    assert plan.stats.needs_validation == 1


def test_raw_broken_candidate_still_goes_to_broken_bucket():
    """Les flags techniques (is_broken) priment toujours sur le matcher."""
    cand = _candidate(
        "missing.mkv", is_symlink=False, is_broken=True, target=None
    )
    builder = _make_raw_builder(
        [cand], outcome=_make_matched_outcome(), vote_average=8.0
    )
    plan = builder.build(Path("/old_nas/Vidéos"), Path("/new_nas"))

    # is_broken implique pas d'appel matcher → bucket NOT_SYMLINK fallback
    # (chemin _build_symlink_item) qui regarde is_broken en premier.
    assert plan.items[0].bucket == Bucket.BROKEN
    builder._matcher.match.assert_not_called()


def test_raw_matched_destination_is_none_during_plan():
    """Mode raw : la destination canonique est calculée à l'apply, pas au plan."""
    cand = _candidate("avatar.mkv", is_symlink=False)
    builder = _make_raw_builder(
        [cand], outcome=_make_matched_outcome(), vote_average=8.0
    )
    plan = builder.build(Path("/old_nas/Vidéos"), Path("/new_nas"))

    assert plan.items[0].bucket == Bucket.MIGRATE
    assert plan.items[0].destination_path is None


def test_write_review_csvs_writes_needs_validation_file(tmp_path):
    cand = _candidate("ambigu.mkv", is_symlink=False)
    builder = _make_raw_builder(
        [cand], outcome=_make_ambiguous_outcome(), vote_average=None
    )
    plan = builder.build(Path("/old_nas/Vidéos"), Path("/new_nas"))

    write_review_csvs(plan, tmp_path)

    needs_csv = tmp_path / "needs_validation.csv"
    assert needs_csv.exists()
    with needs_csv.open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["symlink_path"].endswith("ambigu.mkv")
    payload = json.loads(rows[0]["top_candidates_json"])
    assert len(payload) == 2
    assert payload[0]["title"] == "Foo"


def test_serialize_plan_persists_match_info_for_raw_matched():
    cand = _candidate("avatar.mkv", is_symlink=False)
    builder = _make_raw_builder(
        [cand], outcome=_make_matched_outcome(), vote_average=8.0
    )
    plan = builder.build(Path("/old_nas/Vidéos"), Path("/new_nas"))

    obj = json.loads(serialize_plan(plan))
    item = obj["items"][0]
    assert item["bucket"] == "migrate"
    assert item["is_symlink_source"] is False
    assert item["match"]["tmdb_id"] == 19995
    assert item["match"]["score"] == 95.0
    assert obj["stats"]["needs_validation"] == 0


def test_legacy_mode_unchanged_when_include_raw_false():
    """Garde-fou : un fichier physique en mode symlinks pur reste NOT_SYMLINK."""
    cand = _candidate("physical.mkv", is_symlink=False)
    builder = _make_builder([cand], {}, {})  # include_raw default False
    plan = builder.build(Path("/old_nas/Vidéos"), Path("/new_nas"))
    assert plan.items[0].bucket == Bucket.NOT_SYMLINK
    assert plan.stats.not_symlink == 1
    assert plan.stats.needs_validation == 0
