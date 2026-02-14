"""
Methodes d'execution des corrections cleanup.

Regroupe les actions correctives : reparation de symlinks,
suppression, deplacement, subdivision et nettoyage de repertoires.
"""

from pathlib import Path
from typing import Any

from .dataclasses import (
    BrokenSymlinkInfo,
    CleanupResult,
    DuplicateSymlink,
    MisplacedSymlink,
    SubdivisionPlan,
)
from .subdivision_algorithm import _refine_out_of_range_dest


def repair_broken_symlinks(
    broken: list[BrokenSymlinkInfo],
    repair_service: Any,
    min_score: float = 90.0,
) -> CleanupResult:
    """
    Repare les symlinks casses ayant un candidat avec score suffisant.

    Args:
        broken: Liste des symlinks casses a reparer.
        repair_service: Service de reparation des symlinks.
        min_score: Score minimum pour auto-reparation.

    Returns:
        CleanupResult avec les compteurs de reparation.
    """
    result = CleanupResult()

    for info in broken:
        if info.best_candidate is None or info.candidate_score < min_score:
            continue

        try:
            success = repair_service.repair_symlink(
                info.symlink_path, info.best_candidate
            )
            if success:
                result.repaired_symlinks += 1
            else:
                result.failed_repairs += 1
        except Exception as e:
            result.failed_repairs += 1
            result.errors.append(f"Reparation echouee {info.symlink_path}: {e}")

    return result


def delete_broken_symlinks(
    broken: list[BrokenSymlinkInfo],
) -> CleanupResult:
    """
    Supprime les symlinks casses irreparables.

    Args:
        broken: Liste des symlinks casses a supprimer.

    Returns:
        CleanupResult avec le nombre de symlinks supprimes.
    """
    result = CleanupResult()

    for info in broken:
        try:
            info.symlink_path.unlink()
            result.broken_symlinks_deleted += 1
        except FileNotFoundError:
            result.errors.append(f"Symlink deja absent {info.symlink_path}")
        except Exception as e:
            result.errors.append(f"Suppression echouee {info.symlink_path}: {e}")

    return result


def fix_misplaced_symlinks(
    misplaced: list[MisplacedSymlink],
    video_file_repo: Any,
) -> CleanupResult:
    """
    Deplace les symlinks mal places vers le bon repertoire.

    Args:
        misplaced: Liste des symlinks a deplacer.
        video_file_repo: Repository des fichiers video.

    Returns:
        CleanupResult avec le nombre de symlinks deplaces.
    """
    result = CleanupResult()

    for info in misplaced:
        try:
            info.expected_dir.mkdir(parents=True, exist_ok=True)
            new_path = info.expected_dir / info.symlink_path.name
            info.symlink_path.rename(new_path)
            video_file_repo.update_symlink_path(info.symlink_path, new_path)
            result.moved_symlinks += 1
        except Exception as e:
            result.errors.append(f"Deplacement echoue {info.symlink_path}: {e}")

    return result


def fix_duplicate_symlinks(
    duplicates: list[DuplicateSymlink],
) -> CleanupResult:
    """
    Supprime les symlinks dupliques en ne gardant que le plus complet.

    Args:
        duplicates: Liste des groupes de symlinks dupliques.

    Returns:
        CleanupResult avec le nombre de symlinks supprimes.
    """
    result = CleanupResult()

    for dup in duplicates:
        for link in dup.remove:
            try:
                link.unlink()
                result.duplicate_symlinks_removed += 1
            except FileNotFoundError:
                result.errors.append(f"Symlink deja absent {link}")
            except Exception as e:
                result.errors.append(f"Suppression echouee {link}: {e}")

    return result


def subdivide_oversized_dirs(
    plans: list[SubdivisionPlan],
    video_file_repo: Any,
) -> CleanupResult:
    """
    Subdivise les repertoires surcharges selon les plans fournis.

    Deux phases pour garantir que les items hors-plage atterrissent dans
    les nouvelles subdivisions (et non a la racine du frere) :
    1. Creer toutes les subdivisions et deplacer les items in-range
    2. Deplacer les items hors-plage en recalculant la destination

    Args:
        plans: Liste des plans de subdivision.
        video_file_repo: Repository des fichiers video.

    Returns:
        CleanupResult avec les compteurs de subdivision.
    """
    result = CleanupResult()

    # Phase 1 : toutes les subdivisions d'abord
    all_out_of_range: list[tuple[Path, Path]] = []
    for plan in plans:
        try:
            # Creer les sous-repertoires
            dest_dirs = set()
            for _, dest in plan.items_to_move:
                dest_dirs.add(dest.parent)

            for dest_dir in dest_dirs:
                dest_dir.mkdir(parents=True, exist_ok=True)

            # Deplacer les symlinks in-range vers les subdivisions
            for source, dest in plan.items_to_move:
                try:
                    source.rename(dest)
                    video_file_repo.update_symlink_path(source, dest)
                    result.symlinks_redistributed += 1
                except Exception as e:
                    result.errors.append(f"Deplacement echoue {source}: {e}")

            all_out_of_range.extend(plan.out_of_range_items)
            result.subdivisions_created += 1
        except Exception as e:
            result.errors.append(f"Subdivision echouee {plan.parent_dir}: {e}")

    # Phase 2 : deplacer les items hors-plage
    for source, planned_dest in all_out_of_range:
        actual_dest = _refine_out_of_range_dest(planned_dest)
        try:
            actual_dest.parent.mkdir(parents=True, exist_ok=True)
            source.rename(actual_dest)
            video_file_repo.update_symlink_path(source, actual_dest)
            result.symlinks_redistributed += 1
        except Exception as e:
            result.errors.append(f"Deplacement hors-plage echoue {source}: {e}")

    return result


def clean_empty_dirs(empty_dirs: list[Path]) -> CleanupResult:
    """
    Supprime les repertoires vides.

    Args:
        empty_dirs: Liste des repertoires vides a supprimer.

    Returns:
        CleanupResult avec le nombre de repertoires supprimes.
    """
    result = CleanupResult()

    # Trier par profondeur decroissante pour supprimer les plus profonds d'abord
    sorted_dirs = sorted(empty_dirs, key=lambda p: len(p.parts), reverse=True)

    for dirpath in sorted_dirs:
        try:
            dirpath.rmdir()
            result.empty_dirs_removed += 1
        except OSError as e:
            result.errors.append(f"Suppression echouee {dirpath}: {e}")

    return result
