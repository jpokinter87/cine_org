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
from unittest.mock import MagicMock

import pytest

from src.services.migration.dataclasses import (
    Bucket,
    MigrationCandidate,
    MigrationItem,
    MigrationPlan,
    MigrationStats,
    RatingDecision,
)
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
