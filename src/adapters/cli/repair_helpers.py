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
- Mode automatique de réparation
"""

from pathlib import Path
from typing import TYPE_CHECKING, Optional

from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)
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


class AutoRepair:
    """
    Gestion du mode automatique de réparation.

    Responsabilites:
    - Boucle de réparation automatique avec Progress
    - Réparation des symlinks avec score >= 90%
    - Comptage des statistiques (reparés, ignorés, sans candidat)
    """

    @staticmethod
    async def run(
        repair: "RepairService",
        broken: list[Path],
        min_score: float,
        dry_run: bool,
    ) -> tuple[list[RepairAction], int, int]:
        """
        Exécute le mode automatique de réparation.

        Args:
            repair: RepairService
            broken: Liste des symlinks casses
            min_score: Score minimum pour réparation
            dry_run: Mode simulation

        Returns:
            Tuple (actions, auto_repaired, no_match_count)
        """
        from src.adapters.cli.commands import console

        actions: list[RepairAction] = []
        auto_repaired = 0
        no_match_count = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("[cyan]Recherche et reparation...", total=len(broken))

            for link in broken:
                short_name = link.name[:60]
                progress.update(task, description=f"[cyan]{short_name}]")

                # Chercher des cibles possibles avec recherche floue
                targets_with_scores = repair.find_possible_targets(link, min_score=min_score)

                # Reparer si score >= 90%
                if targets_with_scores and targets_with_scores[0][1] >= 90:
                    best_target, best_score = targets_with_scores[0]
                    if not dry_run:
                        success = repair.repair_symlink(link, best_target)
                    else:
                        success = True

                    if success:
                        actions.append(
                            RepairAction(
                                link=link,
                                action=RepairActionType.REPAIRED,
                                new_target=best_target,
                            )
                        )
                        auto_repaired += 1
                        # Afficher en vert au-dessus de la barre
                        progress.console.print(f"[green]✓[/green] {short_name}")
                else:
                    if not targets_with_scores:
                        no_match_count += 1
                        # Afficher en rouge au-dessus de la barre
                        progress.console.print(f"[red]✗[/red] {short_name}")
                    else:
                        # Afficher en jaune au-dessus de la barre
                        progress.console.print(f"[yellow]~[/yellow] {short_name}")
                    actions.append(RepairAction(link=link, action=RepairActionType.SKIPPED))

                progress.advance(task)

            progress.update(task, description="[green]Termine")

        return actions, auto_repaired, no_match_count

    @staticmethod
    def display_summary(auto_repaired: int, broken_count: int, no_match_count: int) -> None:
        """
        Affiche le résumé des réparations automatiques.

        Args:
            auto_repaired: Nombre de symlinks réparés
            broken_count: Nombre total de symlinks casses
            no_match_count: Nombre sans candidat
        """
        from src.adapters.cli.commands import console

        console.print(f"\n[bold]Reparations automatiques:[/bold]")
        console.print(f"  [green]{auto_repaired}[/green] repare(s) (score >= 90%)")
        console.print(f"  [yellow]{broken_count - auto_repaired - no_match_count}[/yellow] ignore(s) (score < 90%)")
        console.print(f"  [red]{no_match_count}[/red] sans candidat")


class InteractiveRepair:
    """
    Gestion du mode interactif de réparation.

    Responsabilites:
    - Boucle interactive pour chaque symlink casse
    - Gestion de la pagination des candidats
    - Recherche personnalisée par titre
    - Gestion du suivi des échecs par série
    - Affichage du résumé final
    """

    def __init__(self) -> None:
        """Initialise le gestionnaire interactif."""
        self.series_failures: dict[str, int] = {}
        self.skipped_series: set[str] = set()

    async def run(
        self,
        repair: "RepairService",
        broken: list[Path],
        min_score: float,
        dry_run: bool,
    ) -> list[RepairAction]:
        """
        Exécute le mode interactif de réparation.

        Args:
            repair: RepairService
            broken: Liste des symlinks casses
            min_score: Score minimum
            dry_run: Mode simulation

        Returns:
            Liste des actions effectuées
        """
        from src.adapters.cli.commands import console
        from src.services.integrity import RepairActionType

        actions: list[RepairAction] = []

        for i, link in enumerate(broken, 1):
            # Verifier si cette serie doit etre ignoree
            series_name = extract_series_name(link)
            if series_name and series_name in self.skipped_series:
                actions.append(RepairAction(link=link, action=RepairActionType.SKIPPED))
                continue

            # Afficher les infos du lien
            console.print(f"\n[dim]({i}/{len(broken)})[/dim]")

            # Chercher des cibles possibles avec recherche floue
            with console.status(f"[cyan]Recherche de candidats pour {link.name}..."):
                targets_with_scores = repair.find_possible_targets(link, min_score=min_score)

            # Afficher le panel avec les infos du lien
            display_broken_link_info(console, link)

            # Pagination des candidats
            page_start = 0

            if targets_with_scores:
                # Auto-reparation si score = 100%
                if targets_with_scores[0][1] >= 100:
                    best_target, best_score = targets_with_scores[0]
                    console.print(f"\n[green]Match parfait (100%)[/green]: {best_target.name}")
                    if not dry_run:
                        success = repair.repair_symlink(link, best_target)
                    else:
                        success = True

                    if success:
                        actions.append(
                            RepairAction(
                                link=link,
                                action=RepairActionType.REPAIRED,
                                new_target=best_target,
                            )
                        )
                        # Reinitialiser le compteur d'echecs pour cette serie
                        if series_name and series_name in self.series_failures:
                            self.series_failures[series_name] = 0
                        console.print(f"[green]✓ Auto-repare -> {best_target.name}[/green]\n")
                    else:
                        console.print("[red]Echec de la reparation automatique[/red]\n")
                    continue  # Passer au symlink suivant

                console.print(f"\n[green]{len(targets_with_scores)}[/green] cible(s) possible(s):")
                CandidateDisplay.display(console, targets_with_scores, page_start)

            # Boucle pour gerer la pagination et recherche par titre
            result = await self._process_link(
                repair, link, targets_with_scores, page_start, min_score, dry_run, series_name
            )

            if result == "quit":
                console.print("[yellow]Reparation interrompue.[/yellow]")
                break
            elif result == "repair":
                actions.append(result["action"])
                if series_name:
                    self.series_failures[series_name] = 0
            elif result == "skip":
                actions.append(result["action"])
                if series_name:
                    self._handle_skip(series_name)
            elif result == "orphan":
                actions.append(result["action"])

        return actions

    async def _process_link(
        self,
        repair: "RepairService",
        link: Path,
        targets_with_scores: list,
        page_start: int,
        min_score: float,
        dry_run: bool,
        series_name: str | None,
    ) -> str | dict:
        """
        Traite un symlink casse de manière interactive.

        Returns:
            "quit", "repair", "skip", "orphan", ou dict avec l'action
        """
        from src.adapters.cli.commands import console
        from src.services.integrity import RepairAction, RepairActionType

        while True:
            # Prompt interactif avec raccourcis
            valid_choices = {"r", "s", "i", "q", "t"}  # t = rechercher par titre
            has_more = CandidateDisplay.has_more(targets_with_scores, page_start)
            if has_more:
                valid_choices.add("p")

            if targets_with_scores:
                default = "r" if targets_with_scores[0][1] >= 70 else "i"
                options = "[green]r[/green]=reparer  [yellow]s[/yellow]=supprimer  [dim]i[/dim]=ignorer  [red]q[/red]=quitter  [magenta]t[/magenta]=titre"
                if has_more:
                    options += "  [cyan]p[/cyan]=plus"
            else:
                default = "i"
                options = "[yellow]s[/yellow]=supprimer  [dim]i[/dim]=ignorer  [red]q[/red]=quitter  [magenta]t[/magenta]=titre"

            console.print(f"\n{options}")
            choice = input(f"Action [{default}]: ").strip().lower() or default

            # Valider le choix
            if choice not in valid_choices:
                console.print(f"[red]Choix invalide. Utilisez: {', '.join(sorted(valid_choices))}[/red]")
                continue

            # Recherche par titre personnalise
            if choice == "t":
                custom_title = input("Titre a rechercher: ").strip()
                if custom_title:
                    console.print(f"[cyan]Recherche de '{custom_title}'...[/cyan]")

                    # Utiliser CustomSearch pour la recherche
                    custom_results = CustomSearch.search(repair, custom_title, link, min_score)

                    if custom_results:
                        targets_with_scores = custom_results
                        page_start = 0
                        media_label = "films" if "/films/" in str(link).lower() else "séries" if "/séries/" in str(link).lower() or "/series/" in str(link).lower() else "tous"
                        console.print(f"\n[green]{len(targets_with_scores)}[/green] resultat(s) pour '{custom_title}' ({media_label}):")
                        CandidateDisplay.display(console, targets_with_scores, page_start)
                    else:
                        console.print(f"[red]Aucun resultat pour '{custom_title}'[/red]")
                continue

            # Gerer la pagination
            if choice == "p":
                page_start += CandidateDisplay.PAGE_SIZE
                console.print("")
                CandidateDisplay.display(console, targets_with_scores, page_start)
                continue

            if choice == "q":
                return "quit"

            elif choice == "i":
                action = RepairAction(link=link, action=RepairActionType.SKIPPED)
                console.print("[dim]Ignore[/dim]")

                # Compter les echecs pour cette serie
                if series_name:
                    self.series_failures[series_name] = self.series_failures.get(series_name, 0) + 1

                    # Apres 3 echecs, proposer d'ignorer toute la serie
                    if self.series_failures[series_name] == 3:
                        await self._propose_skip_series(link, series_name, dry_run)
                console.print("")
                return {"action": action, "series_name": series_name}

            elif choice == "s":
                action = await self._handle_orphan(repair, link, dry_run)
                if action:
                    return {"action": action}

            elif choice == "r":
                if not targets_with_scores:
                    console.print("[red]Aucune cible trouvee[/red]\n")
                    return {"action": RepairAction(link=link, action=RepairActionType.SKIPPED)}

                # Selection de la cible
                max_choice = min(len(targets_with_scores), 15)
                target_choice = input(f"Cible (1-{max_choice}, a=annuler) [1]: ").strip().lower() or "1"

                if target_choice == "a" or target_choice == "annuler":
                    return {"action": RepairAction(link=link, action=RepairActionType.SKIPPED)}
                else:
                    try:
                        target_idx = int(target_choice) - 1
                        if target_idx < 0 or target_idx >= len(targets_with_scores):
                            console.print(f"[red]Choix invalide (1-{max_choice})[/red]\n")
                            return {"action": RepairAction(link=link, action=RepairActionType.SKIPPED)}
                    except ValueError:
                        console.print(f"[red]Choix invalide (1-{max_choice} ou 'a')[/red]\n")
                        return {"action": RepairAction(link=link, action=RepairActionType.SKIPPED)}
                    new_target, score = targets_with_scores[target_idx]

                    if dry_run:
                        console.print(f"[cyan](dry-run)[/cyan] Reparation: {new_target.name}\n")
                        return {"action": RepairAction(link=link, action=RepairActionType.REPAIRED, new_target=new_target)}
                    else:
                        success = repair.repair_symlink(link, new_target)

                        if success:
                            # Reinitialiser le compteur d'echecs
                            if series_name and series_name in self.series_failures:
                                self.series_failures[series_name] = 0
                            console.print(f"[green]Repare -> {new_target.name}[/green]\n")
                            return {"action": RepairAction(link=link, action=RepairActionType.REPAIRED, new_target=new_target)}
                        else:
                            console.print("[red]Echec de la reparation[/red]\n")
                            return {"action": RepairAction(link=link, action=RepairActionType.SKIPPED)}

    async def _propose_skip_series(self, link: Path, series_name: str, dry_run: bool) -> None:
        """Propose d'ignorer toute la série après 3 échecs."""
        # Compter combien d'episodes restants pour cette serie
        # (ceci nécessite la liste complète des broken, que nous n'avons pas ici)
        # Pour simplifier, nous allons juste proposer d'ignorer
        console.print(
            f"\n[yellow]3 echecs consecutifs pour '{series_name}'.[/yellow]"
        )

        # Utiliser la même fonction que dans le code original pour compter les episodes restants
        # (nous avons besoin de la liste complète, ce qui n'est pas passée en paramètre)

        skip_all = input(
            f"Ignorer les episodes restants de cette serie ? (o/n) [n]: "
        ).strip().lower()
        if skip_all == "o" or skip_all == "oui":
            self.skipped_series.add(series_name)
            console.print(f"[dim]Serie '{series_name}' ignoree.[/dim]")

    def _handle_skip(self, series_name: str) -> None:
        """Gère le compteur d'échecs pour une série."""
        self.series_failures[series_name] = self.series_failures.get(series_name, 0) + 1

    async def _handle_orphan(self, repair: "RepairService", link: Path, dry_run: bool) -> RepairAction | None:
        """Gère le déplacement vers orphans."""
        from src.adapters.cli.commands import console
        from src.services.integrity import RepairAction, RepairActionType

        if dry_run:
            console.print(f"[cyan](dry-run)[/cyan] Deplacement vers orphans\n")
            return RepairAction(link=link, action=RepairActionType.ORPHANED)
        else:
            dest = repair.move_to_orphans(link)
            if dest:
                console.print(f"[yellow]Deplace vers orphans[/yellow]\n")
                return RepairAction(link=link, action=RepairActionType.ORPHANED)
            else:
                console.print("[red]Echec du deplacement[/red]\n")
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
