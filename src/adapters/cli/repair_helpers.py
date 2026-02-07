"""
Helpers CLI pour la commande repair-links.

Ce module fournit les fonctions utilitaires pour l'interface interactive
de reparation des symlinks casses.

Responsabilites:
- Extraction du nom de serie depuis un chemin
- Affichage des candidats de reparation
- Gestion de la pagination des candidats
- Recherche personnalisée par titre
- Boucle interactive de reparation
"""

from pathlib import Path
from typing import TYPE_CHECKING, Optional

from rich.panel import Panel
from rich.status import Status

from src.services.integrity import RepairAction, RepairActionType

if TYPE_CHECKING:
    from src.services.integrity import RepairService


def extract_series_name(path: Path) -> Optional[str]:
    """
    Extrait le nom de la serie depuis le chemin du symlink.

    Analyse le chemin pour trouver le nom de la serie en ignorant
    les subdivisions alphabetiques et les types de series.

    Args:
        path: Chemin du symlink

    Returns:
        Le nom de la serie ou None si pas trouve
    """
    parts = path.parts
    for i, part in enumerate(parts):
        if part.lower() in ("séries", "series"):
            # Le nom de la serie est generalement 2-3 niveaux apres
            # Ex: Séries/Séries TV/A-M/Breaking Bad/Saison 01/...
            for j in range(i + 1, min(i + 5, len(parts))):
                # Ignorer les subdivisions alphabetiques et types
                if parts[j] in ("Séries TV", "Animation", "Mangas"):
                    continue
                if len(parts[j]) <= 3 and "-" in parts[j]:
                    continue  # Subdivision A-M, etc.
                if parts[j].startswith("Saison"):
                    break
                return parts[j]
    return None


class CandidateDisplay:
    """
    Gestion de l'affichage des candidats de reparation.

    Responsabilites:
    - Affichage pagine des candidats
    - Coloration selon le score
    - Affichage des details (chemin parent)
    """

    PAGE_SIZE = 5

    @staticmethod
    def display(console, targets_with_scores: list[tuple[Path, float]], start: int = 0) -> None:
        """
        Affiche une page de candidats.

        Args:
            console: Console Rich pour l'affichage
            targets_with_scores: Liste des (cible, score)
            start: Index de debut de la page
        """
        end = min(start + CandidateDisplay.PAGE_SIZE, len(targets_with_scores))
        for j, (target, score) in enumerate(targets_with_scores[start:end], start + 1):
            score_color = "green" if score >= 80 else "yellow" if score >= 60 else "red"
            console.print(
                f"  {j}. [{score_color}]{score:.0f}%[/{score_color}] {target.name}"
            )
            console.print(f"     [dim]{target.parent}[/dim]")
        remaining = len(targets_with_scores) - end
        if remaining > 0:
            console.print(f"  [dim]... et {remaining} autre(s) (tapez 'plus' pour voir)[/dim]")

    @staticmethod
    def has_more(targets_with_scores: list[tuple[Path, float]], page_start: int) -> bool:
        """Indique s'il y a plus de candidats a afficher."""
        return targets_with_scores and page_start + CandidateDisplay.PAGE_SIZE < len(targets_with_scores)


class CustomSearch:
    """
    Recherche personnalisée par titre.

    Responsabilites:
    - Recherche par titre personnalisé
    - Filtrage par type de media
    - Calcul des scores de similarité
    """

    @staticmethod
    def search(
        repair_service: "RepairService",
        custom_title: str,
        link_path: Path,
        min_score: float,
    ) -> list[tuple[Path, float]]:
        """
        Recherche des cibles par titre personnalisé.

        Args:
            repair_service: RepairService avec l'index des fichiers
            custom_title: Titre a rechercher
            link_path: Chemin du symlink casse (pour determiner le type)
            min_score: Score minimum

        Returns:
            Liste des (cible, score) triee par score decroissant
        """
        from difflib import SequenceMatcher

        # Detecter le type de media pour filtrer
        link_str = str(link_path).lower()
        is_film = "/films/" in link_str
        is_series = "/séries/" in link_str or "/series/" in link_str

        # Recherche dans l'index avec le titre personnalise
        custom_clean = repair_service._extract_clean_title(custom_title)
        custom_results: list[tuple[Path, float]] = []

        for candidate_path, candidate_norm, candidate_clean in repair_service._file_index:
            # Filtrer par type de media
            candidate_str = str(candidate_path).lower()
            if is_film and ("/séries/" in candidate_str or "/series/" in candidate_str):
                continue
            if is_series and "/films/" in candidate_str:
                continue

            # Calculer la similarite avec le titre personnalise
            ratio = SequenceMatcher(None, custom_clean, candidate_clean).ratio()
            score = ratio * 100
            if score >= min_score:
                custom_results.append((candidate_path, score))

        custom_results.sort(key=lambda x: x[1], reverse=True)
        return custom_results[:15]


class RepairSummary:
    """
    Affichage du resume de reparation.

    Responsabilites:
    - Affichage du resume des actions
    - Comptage par type d'action
    - Sauvegarde du log
    """

    @staticmethod
    def display(console, actions: list[RepairAction]) -> None:
        """
        Affiche le resume de la reparation.

        Args:
            console: Console Rich pour l'affichage
            actions: Liste des actions effectuees
        """
        repaired = sum(1 for a in actions if a.action == RepairActionType.REPAIRED)
        orphaned = sum(1 for a in actions if a.action == RepairActionType.ORPHANED)
        skipped = sum(1 for a in actions if a.action == RepairActionType.SKIPPED)

        console.print("\n[bold]Resume:[/bold]")
        console.print(f"  [green]{repaired}[/green] repare(s)")
        console.print(f"  [yellow]{orphaned}[/yellow] deplace(s) vers orphans")
        console.print(f"  [dim]{skipped} ignore(s)[/dim]")


def display_broken_link_info(console, link: Path) -> None:
    """
    Affiche les informations d'un symlink casse.

    Args:
        console: Console Rich pour l'affichage
        link: Chemin du symlink casse
    """
    try:
        original_target = link.readlink()
    except OSError:
        original_target = Path("<inconnu>")

    panel_content = [
        f"[bold]{link.name}[/bold]",
        f"Chemin: {link}",
        f"Cible originale: [red]{original_target}[/red]",
    ]
    console.print(Panel("\n".join(panel_content), title="Symlink casse"))
