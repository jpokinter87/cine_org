"""
Recherche personnalisee et affichage des candidats de reparation.

Fournit la recherche par titre et l'affichage pagine des candidats.
"""

from pathlib import Path
from typing import TYPE_CHECKING

from src.services.integrity import RepairAction, RepairActionType

if TYPE_CHECKING:
    from src.services.repair import RepairService


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
