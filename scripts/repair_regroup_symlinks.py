"""
Script de réparation des symlinks brisés par le bug de regroup --fix.

Phase 1 : Matching direct (fichiers NAS orphelins dans le répertoire parent)
Phase 2 : Recherche élargie via RepairService pour Films et Séries
Phase 3 : Rapport des cas irrecouvrables

Usage:
    python scripts/repair_regroup_symlinks.py --dry-run    # Analyse sans modification
    python scripts/repair_regroup_symlinks.py --fix         # Appliquer les réparations
"""

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

# Ajouter le répertoire racine au path
sys.path.insert(0, str(Path(__file__).parent.parent))

VIDEO_DIR = Path("/media/Serveur/test")
NAS_DIR = Path("/media/NAS64")


def normalize(name: str) -> str:
    """Normalise un nom de fichier pour comparaison."""
    stem = Path(name).stem.lower()
    for sep in [".", "_", "-"]:
        stem = stem.replace(sep, " ")
    return stem


def build_claimed_targets(video_dir: Path) -> set[str]:
    """Construit l'ensemble des cibles NAS pointées par des symlinks fonctionnels."""
    claimed = set()
    for root, dirs, files in os.walk(str(video_dir)):
        for name in files:
            full = Path(root) / name
            if full.is_symlink():
                target = os.readlink(str(full))
                if os.path.isabs(target) and os.path.exists(target):
                    claimed.add(os.path.realpath(target))
    return claimed


def find_regroup_broken(video_dir: Path) -> list[tuple[str, str]]:
    """Trouve les symlinks brisés par le regroup (nom cible == nom symlink)."""
    broken = []
    for root, dirs, files in os.walk(str(video_dir)):
        for name in files:
            full = Path(root) / name
            if full.is_symlink():
                target = os.readlink(str(full))
                if os.path.isabs(target) and not os.path.exists(target):
                    if Path(target).name == name:
                        broken.append((str(full), target))
    return broken


def match_orphaned_nas(
    broken_links: list[tuple[str, str]],
    claimed_targets: set[str],
    min_score: float = 40.0,
) -> tuple[list[tuple[str, str, str, float]], list[tuple[str, str, str]]]:
    """
    Phase 1 : Matching direct avec les fichiers NAS orphelins du répertoire parent.

    Returns:
        (matched, unmatched) - matched contient (link, old_target, new_target, score)
    """
    by_nas_parent = defaultdict(list)
    for link, target in broken_links:
        nas_parent = str(Path(target).parent.parent)
        by_nas_parent[nas_parent].append((link, target))

    matched = []
    unmatched = []

    for nas_parent, links in sorted(by_nas_parent.items()):
        nas_parent_path = Path(nas_parent)

        if not nas_parent_path.exists():
            for link, target in links:
                unmatched.append((link, target, "NAS parent manquant"))
            continue

        # Fichiers orphelins dans le parent (non réclamés par un symlink fonctionnel)
        orphaned = {}
        try:
            for f in nas_parent_path.iterdir():
                if f.is_file():
                    real = os.path.realpath(str(f))
                    if real not in claimed_targets:
                        orphaned[f.name] = str(f)
        except (PermissionError, OSError):
            for link, target in links:
                unmatched.append((link, target, "Erreur accès NAS parent"))
            continue

        # Chercher aussi dans les sous-répertoires préfixes du NAS
        prefix_dirs = {Path(target).parent.name for _, target in links}
        for prefix_name in prefix_dirs:
            prefix_path = nas_parent_path / prefix_name
            if prefix_path.is_dir():
                try:
                    for f in prefix_path.iterdir():
                        if f.is_file():
                            real = os.path.realpath(str(f))
                            if real not in claimed_targets:
                                orphaned[f"__pfx_{prefix_name}_{f.name}"] = str(f)
                except (PermissionError, OSError):
                    pass

        if not orphaned:
            for link, target in links:
                unmatched.append((link, target, "Aucun fichier orphelin"))
            continue

        # Matcher chaque lien brisé avec le meilleur fichier orphelin
        remaining = dict(orphaned)
        for link, target in links:
            video_name = Path(link).name
            video_ext = Path(video_name).suffix.lower()
            norm_video = normalize(video_name)

            best_match = None
            best_score = 0.0
            best_key = None

            for key, nas_path in remaining.items():
                nas_name = Path(nas_path).name
                if Path(nas_name).suffix.lower() != video_ext:
                    continue
                norm_nas = normalize(nas_name)
                score = SequenceMatcher(None, norm_video, norm_nas).ratio() * 100
                if score > best_score:
                    best_score = score
                    best_match = nas_path
                    best_key = key

            if best_match and best_score >= min_score:
                matched.append((link, target, best_match, best_score))
                del remaining[best_key]
                claimed_targets.add(os.path.realpath(best_match))
            else:
                reason = f"Meilleur score: {best_score:.0f}%" if best_score > 0 else "Aucun fichier orphelin"
                unmatched.append((link, target, reason))

    return matched, unmatched


def apply_repairs(
    matched: list[tuple[str, str, str, float]],
    dry_run: bool = True,
) -> tuple[int, int]:
    """Applique les réparations de symlinks."""
    repaired = 0
    errors = 0

    for link, old_target, new_target, score in matched:
        link_path = Path(link)
        new_target_path = Path(new_target)

        if dry_run:
            repaired += 1
            continue

        try:
            # Supprimer l'ancien symlink brisé
            if link_path.is_symlink():
                link_path.unlink()

            # Créer le nouveau symlink pointant vers le fichier NAS correct
            link_path.symlink_to(new_target_path)
            repaired += 1
        except OSError as e:
            print(f"  ERREUR: {link} -> {e}", file=sys.stderr)
            errors += 1

    return repaired, errors


def cleanup_empty_prefix_dirs(
    matched: list[tuple[str, str, str, float]],
    dry_run: bool = True,
) -> int:
    """Supprime les répertoires préfixes vides créés par le code bugué sur NAS."""
    dirs_to_check = set()
    for _, old_target, _, _ in matched:
        prefix_dir = Path(old_target).parent
        dirs_to_check.add(str(prefix_dir))

    removed = 0
    for dir_path in sorted(dirs_to_check):
        dp = Path(dir_path)
        if dp.exists() and dp.is_dir():
            try:
                items = list(dp.iterdir())
                if not items:
                    if not dry_run:
                        dp.rmdir()
                    removed += 1
            except (PermissionError, OSError):
                pass

    return removed


def save_report(
    matched: list[tuple[str, str, str, float]],
    unmatched: list[tuple[str, str, str]],
    output_path: Path,
) -> None:
    """Sauvegarde le rapport de réparation en JSON."""
    data = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "matched_count": len(matched),
        "unmatched_count": len(unmatched),
        "matched": [
            {
                "link": link,
                "old_target": old_target,
                "new_target": new_target,
                "score": round(score, 1),
            }
            for link, old_target, new_target, score in matched
        ],
        "unmatched": [
            {"link": link, "old_target": target, "reason": reason}
            for link, target, reason in unmatched
        ],
    }
    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description="Répare les symlinks brisés par regroup --fix")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Analyse sans modification")
    group.add_argument("--fix", action="store_true", help="Appliquer les réparations")
    parser.add_argument("--min-score", type=float, default=40.0, help="Score minimum de matching (défaut: 40)")
    args = parser.parse_args()

    dry_run = args.dry_run

    print("=== Réparation des symlinks brisés par regroup --fix ===")
    print()

    # Étape 1 : Indexer les symlinks fonctionnels
    print("Indexation des symlinks fonctionnels...")
    claimed = build_claimed_targets(VIDEO_DIR)
    print(f"  {len(claimed)} cibles NAS réclamées")

    # Étape 2 : Trouver les liens brisés par le regroup
    print("Recherche des symlinks brisés par le regroup...")
    broken = find_regroup_broken(VIDEO_DIR)
    print(f"  {len(broken)} symlinks brisés identifiés")

    if not broken:
        print("\nAucun symlink brisé par le regroup trouvé.")
        return

    # Étape 3 : Phase 1 - Matching direct
    print("\nPhase 1 : Matching direct (orphelins NAS)...")
    matched, unmatched = match_orphaned_nas(broken, claimed, min_score=args.min_score)
    print(f"  {len(matched)} matchés, {len(unmatched)} non résolus")

    # Distribution de confiance
    conf = Counter()
    for _, _, _, score in matched:
        if score >= 90:
            conf["90-100%"] += 1
        elif score >= 70:
            conf["70-89%"] += 1
        elif score >= 50:
            conf["50-69%"] += 1
        else:
            conf["40-49%"] += 1

    print("\n  Distribution de confiance :")
    for r in ["90-100%", "70-89%", "50-69%", "40-49%"]:
        print(f"    {r}: {conf.get(r, 0)}")

    # Raisons des échecs
    reason_counts = Counter(r for _, _, r in unmatched)
    print(f"\n  Raisons des non-résolus :")
    for reason, count in reason_counts.most_common():
        print(f"    {reason}: {count}")

    # Catégories des non-résolus
    cat_counts = Counter()
    for link, _, _ in unmatched:
        rel = os.path.relpath(link, str(VIDEO_DIR))
        cat_counts[rel.split("/")[0]] += 1
    print(f"\n  Non-résolus par catégorie :")
    for cat, count in cat_counts.most_common():
        print(f"    {cat}: {count}")

    # Exemples de matches à basse confiance
    low_conf = [(l, t, n, s) for l, t, n, s in matched if s < 60]
    if low_conf:
        print(f"\n  Matches à basse confiance (<60%) : {len(low_conf)}")
        for link, _, nas, score in low_conf[:5]:
            print(f"    [{score:.0f}%] {Path(link).name}")
            print(f"      -> {Path(nas).name}")

    # Étape 4 : Appliquer les réparations
    mode = "DRY-RUN" if dry_run else "FIX"
    print(f"\n=== {mode} : Réparation de {len(matched)} symlinks ===")

    repaired, errors = apply_repairs(matched, dry_run=dry_run)
    print(f"  Réparés : {repaired}")
    if errors:
        print(f"  Erreurs : {errors}")

    # Nettoyer les répertoires préfixes vides sur NAS
    removed = cleanup_empty_prefix_dirs(matched, dry_run=dry_run)
    print(f"  Répertoires préfixes vides supprimés : {removed}")

    # Sauvegarder le rapport
    report_dir = Path.home() / ".cineorg"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "regroup_repair_report.json"
    save_report(matched, unmatched, report_path)
    print(f"\n  Rapport sauvegardé : {report_path}")

    if unmatched:
        print(f"\n{'='*60}")
        print(f"ATTENTION : {len(unmatched)} symlinks n'ont pas pu être réparés.")
        print("Utiliser `cineorg repair-links` pour une recherche élargie.")


if __name__ == "__main__":
    main()
