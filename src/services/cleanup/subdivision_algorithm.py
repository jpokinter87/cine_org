"""
Algorithme de subdivision des repertoires surcharges.

Fournit les fonctions de calcul de plages alphabetiques, recherche de
repertoires freres, et affinement des destinations hors-plage.
"""

import re
from pathlib import Path

from src.utils.helpers import normalize_accents, strip_article as _strip_article

from .dataclasses import SubdivisionPlan

_normalize_sort_key = normalize_accents


def _parse_parent_range(dir_name: str) -> tuple[str, str]:
    """
    Parse le nom d'un repertoire parent en plage de cles 2 lettres.

    Detecte les patterns de subdivision alphabetique :
    - Lettre simple "C" -> ("CA", "CZ")
    - Plage "E-F" -> ("EA", "FZ")
    - Plage avec prefixe "L-Ma" -> ("LA", "MA")
    - Non-plage "Action", "Drame" -> ("AA", "ZZ")

    Args:
        dir_name: Nom du repertoire parent.

    Returns:
        Tuple (start, end) en majuscules, 2 caracteres chacun.
    """
    # Normaliser les accents avant parsing
    clean = _normalize_sort_key(dir_name)

    # Plage "X-Y" ou "Xx-Yy"
    match = re.match(r"^([A-Za-z]{1,3})-([A-Za-z]{1,3})$", clean)
    if match:
        start_part = match.group(1).upper()
        end_part = match.group(2).upper()
        start = (start_part[0] + "A") if len(start_part) == 1 else (start_part[0] + start_part[1])
        end = (end_part[0] + "Z") if len(end_part) == 1 else (end_part[0] + end_part[1])
        return start, end

    # Lettre simple "C"
    match = re.match(r"^([A-Za-z])$", clean)
    if match:
        letter = match.group(1).upper()
        return f"{letter}A", f"{letter}Z"

    # Non-plage (genre, etc.) -> tout accepter
    return "AA", "ZZ"


def _find_sibling_for_key(parent_dir: Path, sort_key: str) -> Path:
    """
    Trouve le repertoire frere (sibling) qui correspond a une cle de tri.

    Parcourt les repertoires freres de parent_dir et utilise _parse_parent_range
    pour trouver celui dont la plage contient la cle. Si aucun frere ne correspond,
    retourne le grand-parent comme destination de repli.

    Args:
        parent_dir: Repertoire contenant l'item hors plage.
        sort_key: Cle de tri 2 lettres (ex: "JA", "BO", "CH").

    Returns:
        Path du repertoire destination.
    """
    grandparent = parent_dir.parent
    if not grandparent.exists():
        return grandparent

    for sibling in sorted(grandparent.iterdir()):
        if not sibling.is_dir() or sibling == parent_dir:
            continue
        # Ignorer les repertoires non-alphabetiques (ex: '#') dont la plage
        # fallback ("AA","ZZ") capturerait toutes les cles alphabetiques
        if not sibling.name[0].isalpha():
            continue
        sib_start, sib_end = _parse_parent_range(sibling.name)
        if sib_start <= sort_key <= sib_end:
            return sibling

    # Aucun frere ne correspond -> grand-parent
    return grandparent


def _refine_out_of_range_dest(planned_dest: Path) -> Path:
    """
    Affine la destination d'un item hors-plage apres subdivision.

    Si le repertoire cible a ete subdivise, redirige vers la bonne
    sous-division. Ex: C/El Chapo -> C/Ca-Ch/El Chapo.

    Args:
        planned_dest: Destination initialement planifiee (sibling/item_name).

    Returns:
        Destination affinee (dans une subdivision si elle existe).
    """
    target_dir = planned_dest.parent
    item_name = planned_dest.name

    if not target_dir.exists():
        return planned_dest

    # Chercher des sous-repertoires de subdivision (format "Xx-Yy" uniquement)
    # Ignore les repertoires de contenu (series, films) qui ne sont pas des subdivisions
    subdirs = [
        d for d in sorted(target_dir.iterdir())
        if d.is_dir() and not d.is_symlink()
        and _parse_parent_range(d.name) != ("AA", "ZZ")
    ]
    if not subdirs:
        return planned_dest

    # Calculer la cle de tri de l'item
    stripped = _strip_article(item_name).strip()
    stripped = _normalize_sort_key(stripped)
    letters_only = "".join(c for c in stripped if c.isalpha())
    if len(letters_only) >= 2:
        sort_key = letters_only.upper()[:2]
    else:
        sort_key = letters_only.upper().ljust(2, "A")

    # Trouver la subdivision correspondante
    for subdir in subdirs:
        sub_start, sub_end = _parse_parent_range(subdir.name)
        if sub_start <= sort_key <= sub_end:
            return subdir / item_name

    # Aucune subdivision ne correspond, garder la destination planifiee
    return planned_dest


def _refine_plans_destinations(plans: list[SubdivisionPlan]) -> None:
    """
    Affine les destinations hors-plage en utilisant les donnees des autres plans.

    Si un item hors-plage est destine a un repertoire qui sera lui-meme
    subdivise, la destination est mise a jour pour pointer vers la bonne
    subdivision.

    Modifie les plans in-place.
    """
    plan_map = {plan.parent_dir: plan for plan in plans}

    for plan in plans:
        refined = []
        for source, dest in plan.out_of_range_items:
            target_dir = dest.parent
            item_name = dest.name

            if target_dir in plan_map:
                target_plan = plan_map[target_dir]
                # Calculer la cle de tri (meme logique que _calculate_subdivision_ranges)
                stripped = _strip_article(item_name).strip()
                stripped = _normalize_sort_key(stripped)
                letters_only = "".join(c for c in stripped if c.isalpha())
                sort_key = letters_only.upper()[:2] if len(letters_only) >= 2 else letters_only.upper().ljust(2, "A")

                # Trouver la subdivision correspondante dans le plan cible
                for start, end in target_plan.ranges:
                    range_start = (start[0] + "A") if len(start) == 1 else start.upper()
                    range_end = (end[0] + "Z") if len(end) == 1 else end.upper()
                    if range_start <= sort_key <= range_end:
                        range_label = f"{start}-{end}"
                        dest = target_dir / range_label / item_name
                        break

            refined.append((source, dest))
        plan.out_of_range_items = refined


def calculate_subdivision_ranges(
    parent_dir: Path, max_per_subdir: int
) -> SubdivisionPlan:
    """
    Calcule les plages de subdivision pour un repertoire surcharge.

    Algorithme corrige gerant :
    - Equilibrage des groupes (ceil(n/max) groupes)
    - Couverture de la plage parente (Sa-Zz pour un parent S-Z)
    - Exclusion des items hors plage (ex: Jadotville dans S-Z)
    - Pas de chevauchement entre plages (coupure aux frontieres de cles)
    - Normalisation des accents pour le tri
    - Strip des articles (de, du, le, the, etc.)
    - Toujours format "Start-End" (jamais borne unique)

    Args:
        parent_dir: Repertoire a subdiviser.
        max_per_subdir: Nombre max d'elements par sous-repertoire.

    Returns:
        SubdivisionPlan avec les plages, mouvements et items hors plage.
    """
    import math

    # 1. Lister les elements directs (symlinks ou dossiers)
    items = sorted(parent_dir.iterdir())
    items = [i for i in items if i.is_symlink() or i.is_dir()]

    # 2. Pour chaque item : strip article, normaliser accents, extraire cle 2 lettres
    keyed: list[tuple[str, Path]] = []
    for item in items:
        title = item.name
        stripped = _strip_article(title).strip()
        stripped = _normalize_sort_key(stripped)
        # Filtrer la ponctuation pour l'extraction de la cle (ex: "C.B. Strike" -> "CB Strike")
        letters_only = "".join(c for c in stripped if c.isalpha())
        if len(letters_only) >= 2:
            sort_key = letters_only.upper()[:2]
        else:
            sort_key = letters_only.upper().ljust(2, "A")
        keyed.append((sort_key, item))

    # 3. Parser la plage du parent
    parent_start, parent_end = _parse_parent_range(parent_dir.name)

    # 4. Separer items in-range / out-of-range avec destination pour hors-plage
    in_range: list[tuple[str, Path]] = []
    out_of_range: list[tuple[Path, Path]] = []
    for sort_key, item in keyed:
        if parent_start <= sort_key <= parent_end:
            in_range.append((sort_key, item))
        else:
            dest_dir = _find_sibling_for_key(parent_dir, sort_key)
            out_of_range.append((item, dest_dir / item.name))

    # 5. Trier les in-range par cle normalisee
    in_range.sort(key=lambda x: x[0])

    # Cas special : pas d'items in-range
    if not in_range:
        return SubdivisionPlan(
            parent_dir=parent_dir,
            current_count=len(keyed),
            max_allowed=max_per_subdir,
            ranges=[],
            items_to_move=[],
            out_of_range_items=out_of_range,
        )

    # 6. Calculer le nombre de groupes : ceil(total / max_per_subdir)
    total = len(in_range)
    num_groups = math.ceil(total / max_per_subdir)
    if num_groups < 2:
        num_groups = 2  # Au moins 2 groupes si on subdivise

    # 7. Repartir equitablement
    base_size = total // num_groups
    remainder = total % num_groups

    # 8. Construire les groupes avec ajustement aux frontieres de cles
    ranges: list[tuple[str, str]] = []
    moves: list[tuple[Path, Path]] = []

    idx = 0
    for g in range(num_groups):
        group_size = base_size + (1 if g < remainder else 0)
        if group_size == 0:
            continue

        group_end = idx + group_size

        # Ajuster la coupure pour ne pas couper au milieu d'une meme cle
        if g < num_groups - 1 and group_end < total:
            # Deplacer la coupure au changement de cle le plus proche
            current_key = in_range[group_end - 1][0]
            # Si la cle suivante est la meme, avancer
            while group_end < total and in_range[group_end][0] == current_key:
                group_end += 1
            # Si on a absorbe tous les items restants, reculer
            if group_end >= total and g < num_groups - 1:
                # Essayer de reculer plutot
                group_end = idx + group_size
                current_key = in_range[group_end - 1][0]
                while group_end > idx + 1 and in_range[group_end - 1][0] == current_key:
                    group_end -= 1

        group = in_range[idx:group_end]
        if not group:
            continue

        # 9. Calculer les bornes du groupe
        if g == 0:
            start_key = parent_start
        else:
            start_key = group[0][0]

        if g == num_groups - 1 or group_end >= total:
            end_key = parent_end
        else:
            end_key = group[-1][0]

        # Formater en Capitalized (premiere lettre majuscule, reste minuscule)
        start_label = start_key[0].upper() + start_key[1:].lower()
        end_label = end_key[0].upper() + end_key[1:].lower()

        range_label = f"{start_label}-{end_label}"
        dest = parent_dir / range_label

        for _, item in group:
            moves.append((item, dest / item.name))

        ranges.append((start_label, end_label))

        idx = group_end
        # Si on a epuise tous les items, on arrete
        if idx >= total:
            break

    return SubdivisionPlan(
        parent_dir=parent_dir,
        current_count=len(keyed),
        max_allowed=max_per_subdir,
        ranges=ranges,
        items_to_move=moves,
        out_of_range_items=out_of_range,
    )
