"""
Script one-shot pour nettoyer les 14 items en échec du dernier apply.

Étape 1 : drop des 4 La Flor (fichiers source perdus)
Étape 2 : drop des 6 The Leftovers S03 (faux match TMDB, déjà doublons)
Étape 3 : reclassification des 5 doublons en bucket ALREADY_IN_LIBRARY
          avec tag existing:<path> pour les 4 dont on connaît l'emplacement DB.

Modifie plan.json (in-place) + state_store SQLite. À lancer une fois :
    uv run python scripts/fix_apply_failures_2026_05_16.py
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.services.migration.dataclasses import Bucket
from src.services.migration.plan_builder import deserialize_plan, serialize_plan


PLAN_PATH = Path("migration/plan.json")
STATE_PATH = Path("migration/plan.json.state.sqlite")

# Étape 1 — La Flor (4 items, fichiers perdus)
LA_FLOR_IDS = {
    "28acef174fc9ae91": "La.Flor.partie 3",
    "e2684c4399224a25": "La.Flor.partie 1",
    "863a378c0057ea9a": "La.Flor.partie 4",
    "7fb62984af9bd7ae": "La.Flor.partie 2",
}

# Étape 2 — The Leftovers S03 (6 items, doublons déjà identifiés)
LEFTOVERS_IDS = {
    "6d1e8b862b6eb261": "The Leftovers S03E08",
    "702c149d53123fbe": "The Leftovers S03E07",
    "70c46100349ac350": "The Leftovers S03E06",
    "19080d8262076252": "The Leftovers S03E05",
    "9de470ec7e771371": "The Leftovers S03E04",
    "a2c985bf4ce0c30c": "The Leftovers S03E03",
}

TO_DELETE = {**LA_FLOR_IDS, **LEFTOVERS_IDS}

# Étape 3 — 5 doublons à reclassifier en ALREADY_IN_LIBRARY
# Valeur : chemin existant en DB (None si pas connu — sera revu via la
# carte AIL en review).
TO_RECLASSIFY = {
    "a0c2c8cbd021d167": (
        "Mange Tes Morts",
        "/media/NAS64/Films/Drame/H-Q/M/Mab-Man/Mange.Tes.Morts.Tu.Ne.Diras.Point.2014.FRENCH.1080p.WEB.h264-TiMELiNE.mkv",
    ),
    "28746a98024d06c7": (
        "Zillion",
        "/media/NAS64/Films/Policier/M-Z/U-Z/Zillion (2022) MULTi HEVC Dolby Digital Plus 5.1 1080p.mkv",
    ),
    "f686b48bcfcf617b": (
        "The Disaster Artist",
        "/media/NAS64/Films/Comédie dramatique/A-I/Di-E/The Disaster Artist (2017) MULTi-VFF [1080p] HDRip x265.mkv",
    ),
    "4568d199b05cb938": (
        "Harriet",
        "/media/NAS64/Films/Historique/E-H/Harriet - 2019 - MULTI - WEBRIP - 1080P - 10BITS - HDR - X265 - DTS.mkv",
    ),
    "c9442edab66c7b6e": (
        "Harmony (existing inconnu)",
        None,
    ),
}


def main() -> None:
    print("=" * 70)
    print("Nettoyage des items en échec du dernier apply")
    print("=" * 70)

    # === Modification du plan.json ===
    plan = deserialize_plan(PLAN_PATH.read_text(encoding="utf-8"))
    print(f"\nPlan initial : {len(plan.items)} items")

    new_items = []
    dropped_la_flor = 0
    dropped_leftovers = 0
    reclassified = 0
    missing_ids = set(TO_DELETE) | set(TO_RECLASSIFY)

    for item in plan.items:
        if item.item_id in LA_FLOR_IDS:
            print(f"  [DROP-LA-FLOR]  {item.item_id} — {LA_FLOR_IDS[item.item_id]}")
            dropped_la_flor += 1
            missing_ids.discard(item.item_id)
            continue
        if item.item_id in LEFTOVERS_IDS:
            print(f"  [DROP-LEFTOVERS] {item.item_id} — {LEFTOVERS_IDS[item.item_id]}")
            dropped_leftovers += 1
            missing_ids.discard(item.item_id)
            continue
        if item.item_id in TO_RECLASSIFY:
            label, existing = TO_RECLASSIFY[item.item_id]
            item.bucket = Bucket.ALREADY_IN_LIBRARY
            # Retire d'anciens tags existing: avant d'ajouter le nouveau
            item.tags = [t for t in item.tags if not t.startswith("existing:")]
            if existing:
                item.tags.append(f"existing:{existing}")
            print(f"  [→ AIL]         {item.item_id} — {label}"
                  + (" (sans existing:)" if not existing else ""))
            reclassified += 1
            missing_ids.discard(item.item_id)
        new_items.append(item)

    if missing_ids:
        print(f"\n⚠️  IDs introuvables dans le plan : {missing_ids}")
        print("    (déjà supprimés ou plan régénéré ?)")

    plan.items = new_items
    print(f"\nPlan final : {len(plan.items)} items")
    print(f"  - {dropped_la_flor} La Flor droppés")
    print(f"  - {dropped_leftovers} Leftovers droppés")
    print(f"  - {reclassified} reclassifiés en already_in_library")

    PLAN_PATH.write_text(serialize_plan(plan), encoding="utf-8")
    print(f"\n✓ Plan réécrit : {PLAN_PATH}")

    # === Nettoyage du state store ===
    print()
    all_ids = list(set(TO_DELETE) | set(TO_RECLASSIFY))
    placeholders = ",".join("?" for _ in all_ids)
    con = sqlite3.connect(STATE_PATH)
    n_items = con.execute(
        f"DELETE FROM migration_items WHERE item_id IN ({placeholders})",
        all_ids,
    ).rowcount
    n_decisions = con.execute(
        f"DELETE FROM migration_decisions WHERE item_id IN ({placeholders})",
        all_ids,
    ).rowcount
    con.commit()
    con.close()
    print(f"✓ State store : {n_items} migration_items + {n_decisions} migration_decisions purgés")

    print()
    print("=" * 70)
    print("Terminé. Prochaine étape suggérée :")
    print("  uv run cineorg migrate-nas review migration/plan.json --bucket already_in_library")
    print("  → décide [k]eep dest / [d]elete source pour chacun des 5 doublons")
    print("=" * 70)


if __name__ == "__main__":
    main()
