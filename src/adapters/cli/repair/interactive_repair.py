"""
Mode interactif de reparation des symlinks casses.

Gere la boucle interactive pour chaque symlink avec pagination,
recherche personnalisee et suivi des series confirmees.
"""

from pathlib import Path
from typing import TYPE_CHECKING

from src.services.integrity import RepairAction, RepairActionType

from .custom_search import CandidateDisplay, CustomSearch
from .helpers import display_broken_link_info, extract_series_name

if TYPE_CHECKING:
    from src.services.repair import RepairService

    from .title_resolver import TitleResolver


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
        self.skipped_series: set[str] = set()
        self.confirmed_series: dict[str, Path] = {}

    def _get_nas_series_dir(self, target: Path) -> Path:
        """
        Extrait le repertoire serie NAS depuis le chemin d'une cible.

        Cherche le composant 'Saison' dans le chemin et retourne son parent.
        Si aucun composant 'Saison' n'est trouve (ex: documentaires sans
        structure Saison), retourne target.parent comme fallback.

        Args:
            target: Chemin du fichier cible sur le NAS

        Returns:
            Le repertoire de la serie sur le NAS
        """
        for i, part in enumerate(target.parts):
            if part.startswith("Saison"):
                return Path(*target.parts[:i])
        return target.parent

    def _register_confirmed_series(self, link: Path, target: Path) -> None:
        """
        Enregistre une serie comme confirmee apres validation utilisateur.

        Utilise link.parent comme cle (unique par repertoire d'episodes)
        et le repertoire serie NAS comme valeur.

        Args:
            link: Chemin du symlink confirme
            target: Chemin du fichier cible confirme sur le NAS
        """
        nas_dir = self._get_nas_series_dir(target)
        self.confirmed_series[str(link.parent)] = nas_dir

    def _find_episode_in_nas_dir(self, link: Path, nas_dir: Path) -> Path | None:
        """
        Recherche directe d'un episode par numero SxxExx dans le repertoire NAS.

        Utilise quand la recherche standard ne trouve pas de candidat dans
        le repertoire confirme (ex: nom trop court comme "HPI").

        Args:
            link: Chemin du symlink casse (pour extraire le SxxExx)
            nas_dir: Repertoire NAS confirme de la serie

        Returns:
            Le chemin du fichier correspondant ou None
        """
        import re

        match = re.search(r"S(\d+)E(\d+)", link.name, re.IGNORECASE)
        if not match:
            return None

        episode_id = match.group(0).upper()

        if not nas_dir.exists():
            return None

        for candidate in nas_dir.rglob("*"):
            if candidate.is_file() and not candidate.is_symlink():
                if episode_id in candidate.name.upper():
                    return candidate

        return None

    def _check_series_auto_repair(
        self,
        series_name: str | None,
        link: Path,
        targets_with_scores: list[tuple[Path, float]],
    ) -> Path | None:
        """
        Verifie si un episode peut etre auto-repare grace a une confirmation precedente.

        Utilise link.parent comme cle de recherche dans confirmed_series.
        Cherche d'abord parmi les candidats fournis, puis en fallback
        directement dans le repertoire NAS confirme par numero d'episode.

        Args:
            series_name: Nom de la serie (ou None pour les films)
            link: Chemin du symlink casse
            targets_with_scores: Liste des (cible, score)

        Returns:
            Le chemin cible a utiliser pour l'auto-reparation, ou None
        """
        if not series_name:
            return None

        nas_dir = self.confirmed_series.get(str(link.parent))
        if not nas_dir:
            return None

        # Chercher le meilleur candidat dans le repertoire confirme
        nas_dir_str = str(nas_dir)
        for candidate, score in targets_with_scores:
            if str(candidate).startswith(nas_dir_str):
                return candidate

        # Fallback: recherche directe par numero d'episode dans le NAS
        return self._find_episode_in_nas_dir(link, nas_dir)

    async def run(
        self,
        repair: "RepairService",
        broken: list[Path],
        min_score: float,
        dry_run: bool,
        title_resolver: "TitleResolver | None" = None,
    ) -> list[RepairAction]:
        """
        Exécute le mode interactif de réparation.

        Args:
            repair: RepairService
            broken: Liste des symlinks casses
            min_score: Score minimum
            dry_run: Mode simulation
            title_resolver: Resolveur de titres TMDB optionnel

        Returns:
            Liste des actions effectuées
        """
        from src.adapters.cli.helpers import console

        actions: list[RepairAction] = []

        for i, link in enumerate(broken, 1):
            # Verifier si ce repertoire doit etre ignore (serie skippee)
            series_name = extract_series_name(link)
            if series_name and str(link.parent) in self.skipped_series:
                actions.append(RepairAction(link=link, action=RepairActionType.SKIPPED))
                continue

            # Afficher les infos du lien
            console.print(f"\n[dim]({i}/{len(broken)})[/dim]")

            # Obtenir les titres alternatifs via TMDB
            alt_names = []
            if title_resolver:
                alt_names = await title_resolver.get_alternative_names(link)

            # Chercher des cibles possibles avec recherche floue
            with console.status(f"[cyan]Recherche de candidats pour {link.name}..."):
                targets_with_scores = repair.find_possible_targets(
                    link, min_score=min_score, alternative_names=alt_names or None
                )

            # Auto-reparation si serie deja confirmee
            auto_target = self._check_series_auto_repair(series_name, link, targets_with_scores)
            if auto_target:
                if not dry_run:
                    success = repair.repair_symlink(link, auto_target)
                else:
                    success = True

                if success:
                    actions.append(
                        RepairAction(
                            link=link,
                            action=RepairActionType.REPAIRED,
                            new_target=auto_target,
                        )
                    )
                    console.print(
                        f"[dim]({i}/{len(broken)})[/dim] "
                        f"[green]✓ Auto-serie[/green] {link.name}"
                    )
                    continue

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
                        # Enregistrer la serie comme confirmee
                        if series_name:
                            self._register_confirmed_series(link, best_target)
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
            elif result == "skip":
                actions.append(result["action"])
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
        from src.adapters.cli.helpers import console

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

                # Proposer d'ignorer toute la serie
                if series_name:
                    self._propose_skip_series(console, link)
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
                        if series_name:
                            self._register_confirmed_series(link, new_target)
                        console.print(f"[cyan](dry-run)[/cyan] Reparation: {new_target.name}\n")
                        return {"action": RepairAction(link=link, action=RepairActionType.REPAIRED, new_target=new_target)}
                    else:
                        success = repair.repair_symlink(link, new_target)

                        if success:
                            # Enregistrer la serie comme confirmee
                            if series_name:
                                self._register_confirmed_series(link, new_target)
                            console.print(f"[green]Repare -> {new_target.name}[/green]\n")
                            return {"action": RepairAction(link=link, action=RepairActionType.REPAIRED, new_target=new_target)}
                        else:
                            console.print("[red]Echec de la reparation[/red]\n")
                            return {"action": RepairAction(link=link, action=RepairActionType.SKIPPED)}

    def _propose_skip_series(self, console, link: Path) -> None:
        """Propose d'ignorer les episodes restants du meme repertoire."""
        skip_all = input(
            "Ignorer les episodes restants de cette serie ? (o/n) [o]: "
        ).strip().lower() or "o"
        if skip_all in ("o", "oui"):
            self.skipped_series.add(str(link.parent))
            console.print(f"[dim]Serie ignoree ({link.parent.name})[/dim]")

    async def _handle_orphan(self, repair: "RepairService", link: Path, dry_run: bool) -> RepairAction | None:
        """Gère le déplacement vers orphans."""
        from src.adapters.cli.helpers import console

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
