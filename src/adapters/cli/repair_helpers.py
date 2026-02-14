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
    les subdivisions alphabetiques, les types de series et les
    sous-genres documentaires (mots simples comme Science, Geographie...).

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
            is_documentary = False
            for j in range(i + 1, min(i + 7, len(parts))):
                # Ignorer les subdivisions alphabetiques et types connus
                if parts[j] in ("Séries TV", "Animation", "Mangas"):
                    continue
                if parts[j].startswith(("Animation ", "Mangas ")):
                    continue
                # Categorie documentaire : activer le filtrage des sous-genres
                if parts[j].startswith("Séries "):
                    is_documentary = True
                    continue
                if len(parts[j]) <= 3 and ("-" in parts[j] or len(parts[j]) == 1):
                    continue  # Subdivision A-M, lettre unique, etc.
                if parts[j].startswith("Saison"):
                    break
                # Sous-genres documentaires : mots simples sans espace ni chiffre
                if is_documentary and " " not in parts[j] and not any(c.isdigit() for c in parts[j]):
                    continue
                return parts[j]
    return None


class TitleResolver:
    """
    Resolution de titres alternatifs via TMDB.

    Extrait le titre d'un fichier via guessit, recherche sur TMDB,
    et retourne les titres alternatifs (titre original, etc.).
    Utilise un cache pour eviter les appels API redondants.
    """

    def __init__(self, tmdb_client=None) -> None:
        """
        Args:
            tmdb_client: Client TMDB optionnel. Si None, pas de lookup.
        """
        self._tmdb = tmdb_client
        self._cache: dict[str, list[str]] = {}

    async def get_alternative_names(self, link: Path) -> list[str]:
        """
        Retourne les noms alternatifs pour un symlink via TMDB.

        Args:
            link: Chemin du symlink casse

        Returns:
            Liste de noms alternatifs (vide si pas de TMDB ou pas de resultat)
        """
        if not self._tmdb:
            return []

        from guessit import guessit

        # Extraire titre et annee via guessit
        try:
            info = guessit(link.name)
        except Exception:
            return []

        title = info.get("title", "")
        if not title:
            return []

        year = info.get("year")

        # Verifier le cache
        cache_key = f"{title}:{year}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Recherche TMDB (fr-FR : retourne titre original)
        try:
            results = await self._tmdb.search(title, year=year)
        except Exception:
            self._cache[cache_key] = []
            return []

        alternatives: list[str] = []
        seen_titles: set[str] = {title.lower()}

        for result in results[:3]:
            if result.original_title:
                orig = result.original_title
                if orig.lower() not in seen_titles:
                    alt_name = f"{orig} ({year})" if year else orig
                    alternatives.append(alt_name)
                    seen_titles.add(orig.lower())

        # Recherche supplementaire en anglais pour les films non-latins
        # (ex: film HK dont l'original_title est en chinois mais le NAS utilise le titre EN)
        try:
            import httpx
            client = self._tmdb._get_client()
            params = {"query": title, "language": "en-US", "include_adult": "false"}
            response = await client.get("/search/movie", params=params)
            if response.status_code == 200:
                for item in response.json().get("results", [])[:3]:
                    en_title = item.get("title", "")
                    if en_title and en_title.lower() not in seen_titles:
                        alt_name = f"{en_title} ({year})" if year else en_title
                        alternatives.append(alt_name)
                        seen_titles.add(en_title.lower())
        except Exception:
            pass

        self._cache[cache_key] = alternatives
        return alternatives


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
        title_resolver: "TitleResolver | None" = None,
    ) -> tuple[list[RepairAction], int, int]:
        """
        Exécute le mode automatique de réparation.

        Args:
            repair: RepairService
            broken: Liste des symlinks casses
            min_score: Score minimum pour réparation
            dry_run: Mode simulation
            title_resolver: Resolveur de titres TMDB optionnel

        Returns:
            Tuple (actions, auto_repaired, no_match_count)
        """
        from src.adapters.cli.helpers import console

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

                # Obtenir les titres alternatifs via TMDB
                alt_names = []
                if title_resolver:
                    alt_names = await title_resolver.get_alternative_names(link)

                # Chercher des cibles possibles avec recherche floue
                targets_with_scores = repair.find_possible_targets(
                    link, min_score=min_score, alternative_names=alt_names or None
                )

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
        from src.adapters.cli.helpers import console

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
        from src.services.integrity import RepairActionType

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
