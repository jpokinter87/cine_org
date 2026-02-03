"""
Interface CLI interactive de validation avec Rich.

Ce module fournit les fonctions d'affichage et la boucle interactive
pour la validation manuelle des fichiers video.

Responsabilites:
- Affichage des candidats en cartes avec badge RECOMMANDE
- Pagination des resultats de recherche
- Boucle interactive avec selection, skip, trash, recherche, ID externe
- Affichage du batch de transferts avec barre de progression
"""

import re
from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.tree import Tree

from src.core.entities.video import PendingValidation
from src.core.ports.api_clients import MediaDetails, SearchResult

if TYPE_CHECKING:
    from src.services.transferer import (
        ExistingFileInfo,
        SimilarContentInfo,
        TransferResult,
    )
    from src.services.validation import ValidationService


# Console globale pour tous les affichages
console = Console()

# Nombre de candidats par page
PAGE_SIZE = 5


def get_display_filename(pending: PendingValidation) -> str:
    """
    Extrait le nom de fichier a afficher pour un PendingValidation.

    Priorite au symlink (mieux formate) sur le nom du fichier physique (souvent cryptique).

    Args:
        pending: L'entite PendingValidation

    Returns:
        Le nom du fichier a afficher
    """
    if not pending.video_file:
        return "Fichier inconnu"

    # Priorite au symlink qui est generalement bien formate
    # Ex: "Le Film (2020) FR HEVC 1080p.mkv" vs "fhd-xyz.720p.mkv"
    if pending.video_file.symlink_path:
        return pending.video_file.symlink_path.name

    if pending.video_file.filename:
        return pending.video_file.filename

    return "Fichier inconnu"

# Pattern pour detecter un ID IMDB (tt suivi de 7-8 chiffres)
IMDB_PATTERN = re.compile(r"^tt\d{7,8}$", re.IGNORECASE)


class CandidatePaginator:
    """
    Paginateur pour les candidats de recherche.

    Permet de naviguer dans une liste de candidats page par page.

    Attributs:
        candidates: Liste complete des candidats
        page_size: Nombre de candidats par page
        current_page: Index de la page courante (commence a 0)
    """

    def __init__(
        self, candidates: list[SearchResult], page_size: int = PAGE_SIZE
    ) -> None:
        """
        Initialise le paginateur.

        Args:
            candidates: Liste des candidats a paginer
            page_size: Nombre d'elements par page
        """
        self.candidates = candidates
        self.page_size = page_size
        self.current_page = 0

    @property
    def total_pages(self) -> int:
        """Retourne le nombre total de pages."""
        if not self.candidates:
            return 0
        return (len(self.candidates) + self.page_size - 1) // self.page_size

    @property
    def current_items(self) -> list[SearchResult]:
        """Retourne les candidats de la page courante."""
        start = self.current_page * self.page_size
        return self.candidates[start : start + self.page_size]

    def select(self, display_number: int) -> SearchResult | None:
        """
        Selectionne un candidat par son numero d'affichage.

        Args:
            display_number: Numero affiche (1-based, relatif a la page courante)

        Returns:
            Le candidat selectionne ou None si numero invalide.
        """
        # Verifier que le numero est dans les limites de la page courante
        current_items = self.current_items
        if not (1 <= display_number <= len(current_items)):
            return None

        idx = (self.current_page * self.page_size) + display_number - 1
        if 0 <= idx < len(self.candidates):
            return self.candidates[idx]
        return None

    def next_page(self) -> bool:
        """
        Passe a la page suivante.

        Returns:
            True si la page a ete changee, False si deja sur la derniere.
        """
        if self.current_page + 1 < self.total_pages:
            self.current_page += 1
            return True
        return False

    def has_more(self) -> bool:
        """Retourne True s'il y a plus de pages apres la courante."""
        return self.current_page + 1 < self.total_pages


def render_candidate_card(
    candidate: SearchResult, rank: int, is_best: bool = False
) -> Panel:
    """
    Cree un panel Rich representant une carte de candidat (version simple).

    Args:
        candidate: Le candidat a afficher
        rank: Numero d'affichage (1-based)
        is_best: True si c'est le meilleur candidat (badge RECOMMANDE)

    Returns:
        Un Panel Rich avec les informations du candidat.
    """
    # Construire le contenu de la carte
    lines = []

    # Titre en gras
    lines.append(f"[bold]{candidate.title}[/bold]")

    # Annee
    if candidate.year:
        lines.append(f"Annee: {candidate.year}")

    # Score avec couleur (vert >= 85, jaune sinon)
    score_color = "green" if candidate.score >= 85 else "yellow"
    lines.append(f"Score: [{score_color}]{candidate.score:.0f}%[/{score_color}]")

    # Source
    lines.append(f"Source: {candidate.source.upper()}")

    content = "\n".join(lines)

    # Titre du panel avec numero et badge optionnel
    if is_best:
        title = f"[{rank}] [bold green]* RECOMMANDE[/bold green]"
        border_style = "green"
    else:
        title = f"[{rank}]"
        border_style = "white"

    return Panel(content, title=title, border_style=border_style)


def _get_duration_color(file_duration: int, api_duration: int) -> str:
    """
    Determine la couleur selon l'ecart entre durees.

    Args:
        file_duration: Duree du fichier en secondes
        api_duration: Duree depuis l'API en secondes

    Returns:
        Nom de couleur Rich: green, yellow, ou red
    """
    diff = abs(file_duration - api_duration)
    if diff < 5 * 60:  # < 5 minutes
        return "green"
    elif diff < 15 * 60:  # < 15 minutes
        return "yellow"
    else:
        return "red"


def _truncate_text(text: str, max_length: int = 100) -> str:
    """Tronque un texte avec ellipse si necessaire."""
    if not text:
        return ""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def render_enriched_candidate_card(
    candidate: SearchResult,
    rank: int,
    is_best: bool = False,
    details: "MediaDetails | None" = None,
    file_duration_seconds: int | None = None,
) -> Panel:
    """
    Cree un panel Rich enrichi avec synopsis, credits et durees.

    Args:
        candidate: Le candidat a afficher
        rank: Numero d'affichage (1-based)
        is_best: True si c'est le meilleur candidat (badge RECOMMANDE)
        details: Details enrichis depuis l'API (optionnel)
        file_duration_seconds: Duree du fichier local en secondes (optionnel)

    Returns:
        Un Panel Rich avec les informations enrichies du candidat.
    """
    from src.core.ports.api_clients import MediaDetails

    lines = []

    # Titre en gras
    lines.append(f"[bold]{candidate.title}[/bold]")

    # Annee
    if candidate.year:
        lines.append(f"Annee: {candidate.year}")

    # Score avec couleur (vert >= 85, jaune sinon)
    score_color = "green" if candidate.score >= 85 else "yellow"
    lines.append(f"Score: [{score_color}]{candidate.score:.0f}%[/{score_color}]")

    # Source
    lines.append(f"Source: {candidate.source.upper()}")

    # Infos enrichies si disponibles
    if details:
        # Separateur
        lines.append("")

        # Realisateur
        if details.director:
            lines.append(f"[cyan]Realisateur:[/cyan] {details.director}")

        # Acteurs (4 premiers)
        if details.cast:
            cast_str = ", ".join(details.cast[:4])
            lines.append(f"[cyan]Acteurs:[/cyan] {cast_str}")

        # Durees avec code couleur
        if details.duration_seconds or file_duration_seconds:
            api_dur_str = format_duration(details.duration_seconds) if details.duration_seconds else "?"
            file_dur_str = format_duration(file_duration_seconds) if file_duration_seconds else "?"

            if details.duration_seconds and file_duration_seconds:
                color = _get_duration_color(file_duration_seconds, details.duration_seconds)
                lines.append(
                    f"[cyan]Duree:[/cyan] fichier [{color}]{file_dur_str}[/{color}] / "
                    f"TMDB {api_dur_str}"
                )
            elif file_duration_seconds:
                lines.append(f"[cyan]Duree fichier:[/cyan] {file_dur_str}")
            else:
                lines.append(f"[cyan]Duree TMDB:[/cyan] {api_dur_str}")

        # Synopsis tronque
        if details.overview:
            synopsis = _truncate_text(details.overview, 120)
            lines.append("")
            lines.append(f"[dim]{synopsis}[/dim]")

    content = "\n".join(lines)

    # Titre du panel avec numero et badge optionnel
    if is_best:
        title = f"[{rank}] [bold green]* RECOMMANDE[/bold green]"
        border_style = "green"
    else:
        title = f"[{rank}]"
        border_style = "white"

    return Panel(content, title=title, border_style=border_style)


def display_candidates(
    paginator: CandidatePaginator, pending: PendingValidation
) -> None:
    """
    Affiche les candidats de la page courante (version simple).

    Args:
        paginator: Paginateur avec les candidats
        pending: Entite PendingValidation pour afficher le nom du fichier
    """
    # Header avec nom du fichier - utiliser le symlink en priorite (mieux formate)
    filename = get_display_filename(pending)
    console.print(f"\n[bold cyan]Fichier:[/bold cyan] {filename}")
    console.print()

    # Afficher chaque candidat
    for idx, candidate in enumerate(paginator.current_items, start=1):
        # Le premier de la premiere page est le meilleur (recommande)
        is_best = idx == 1 and paginator.current_page == 0
        panel = render_candidate_card(candidate, idx, is_best)
        console.print(panel)

    # Indication de pagination
    if paginator.has_more():
        console.print("[dim]Autres candidats disponibles... (n pour suivant)[/dim]")


def display_enriched_candidates(
    paginator: CandidatePaginator,
    pending: PendingValidation,
    details_map: dict[str, "MediaDetails"],
) -> None:
    """
    Affiche les candidats enrichis avec synopsis, credits et durees.

    Args:
        paginator: Paginateur avec les candidats
        pending: Entite PendingValidation pour afficher le nom du fichier
        details_map: Dict candidate_id -> MediaDetails pour les candidats de la page
    """
    from src.core.ports.api_clients import MediaDetails

    # Header avec nom du fichier - utiliser le symlink en priorite (mieux formate)
    filename = get_display_filename(pending)
    console.print(f"\n[bold cyan]Fichier:[/bold cyan] {filename}")

    # Afficher la duree du fichier
    file_duration = None
    if pending.video_file and pending.video_file.media_info:
        file_duration = pending.video_file.media_info.duration_seconds
        if file_duration:
            console.print(f"[dim]Duree fichier: {format_duration(file_duration)}[/dim]")

    console.print()

    # Afficher chaque candidat avec details enrichis
    for idx, candidate in enumerate(paginator.current_items, start=1):
        is_best = idx == 1 and paginator.current_page == 0
        details = details_map.get(candidate.id)

        panel = render_enriched_candidate_card(
            candidate=candidate,
            rank=idx,
            is_best=is_best,
            details=details,
            file_duration_seconds=file_duration,
        )
        console.print(panel)

    # Indication de pagination
    if paginator.has_more():
        console.print("[dim]Autres candidats disponibles... (n pour suivant)[/dim]")


def display_help() -> None:
    """Affiche l'aide des commandes disponibles."""
    help_text = """
[bold]Commandes disponibles:[/bold]
  [cyan][1-5][/cyan]  Selectionner un candidat par son numero
  [cyan]s[/cyan]      Passer ce fichier (skip)
  [cyan]t[/cyan]      Mettre en corbeille (trash)
  [cyan]r[/cyan]      Recherche manuelle par titre
  [cyan]i[/cyan]      Saisir un ID externe (IMDB, TMDB, TVDB)
  [cyan]v[/cyan]      Visionner le fichier (ouvre le lecteur)
  [cyan]y[/cyan]      YouTube trailer du candidat 1 (ou y2, y3...)
  [cyan]a[/cyan]      Analyser le generique (OCR/IA)
  [cyan]n[/cyan]      Page suivante (si disponible)
  [cyan]?[/cyan]      Afficher cette aide
  [cyan]q[/cyan]      Quitter la validation
"""
    console.print(help_text)


def detect_external_id(user_input: str) -> tuple[str | None, str | None]:
    """
    Detecte le type d'identifiant externe saisi.

    Args:
        user_input: Saisie utilisateur

    Returns:
        Tuple (type_id, valeur) ou (None, None) si non reconnu.
        - type_id: "imdb" pour ttXXXXXXX, "numeric" pour chiffres purs
        - valeur: L'ID normalise
    """
    user_input = user_input.strip()

    # Detection ID IMDB (ttXXXXXXX)
    if IMDB_PATTERN.match(user_input):
        return ("imdb", user_input.lower())

    # Detection ID numerique (TMDB ou TVDB)
    if user_input.isdigit():
        return ("numeric", user_input)

    # Non reconnu
    return (None, None)


# Pattern pour detecter les series dans les noms de fichiers (SxxExx, saison, season, episode)
SERIES_PATTERNS = [
    re.compile(r"[Ss]\d{1,2}[Ee]\d{1,2}"),  # S01E01, s1e1
    re.compile(r"[Ss]aison[\s._]*\d+", re.IGNORECASE),  # Saison 1, saison.1, saison_1
    re.compile(r"[Ss]eason[\s._]*\d+", re.IGNORECASE),  # Season 1, season.1
    re.compile(r"[Ee]pisode[\s._]*\d+", re.IGNORECASE),  # Episode 1, episode.1
    re.compile(r"\b\d{1,2}x\d{1,2}\b"),  # 1x01, 01x01
]


def determine_is_series(pending: PendingValidation) -> bool:
    """
    Determine si le fichier est une serie.

    Priorite:
    1. Si les candidats existants proviennent de TVDB -> True
    2. Si le nom de fichier contient des patterns de serie (SxxExx) -> True
    3. Sinon -> False (defaut film)

    Args:
        pending: L'entite PendingValidation a analyser

    Returns:
        True si serie, False sinon (film par defaut)
    """
    # Priorite 1: Verifier la source des candidats existants
    if pending.candidates:
        for candidate in pending.candidates:
            source = (
                candidate.source if hasattr(candidate, "source")
                else candidate.get("source", "") if isinstance(candidate, dict)
                else ""
            )
            if source == "tvdb":
                return True
            if source == "tmdb":
                return False

    # Priorite 2: Detecter les patterns de serie dans le nom de fichier
    # Utiliser le symlink en priorite (mieux formate)
    if pending.video_file:
        filename = None
        if pending.video_file.symlink_path:
            filename = pending.video_file.symlink_path.name
        elif pending.video_file.filename:
            filename = pending.video_file.filename

        if filename:
            for pattern in SERIES_PATTERNS:
                if pattern.search(filename):
                    return True

    # Par defaut -> film
    return False


async def _fetch_details_for_page(
    paginator: CandidatePaginator, service: "ValidationService"
) -> dict[str, MediaDetails]:
    """
    Recupere les details enrichis pour les candidats de la page courante.

    Args:
        paginator: Paginateur avec les candidats
        service: ValidationService avec acces aux clients API

    Returns:
        Dict mapping candidate_id -> MediaDetails
    """
    details_map: dict[str, MediaDetails] = {}

    for candidate in paginator.current_items:
        try:
            details = await service._get_details_from_source(
                candidate.source, candidate.id
            )
            if details:
                details_map[candidate.id] = details
        except Exception:
            # En cas d'erreur API, on continue sans les details
            pass

    return details_map


async def validation_loop(
    pending: PendingValidation, service: "ValidationService"
) -> str | None:
    """
    Boucle interactive de validation pour un fichier.

    Args:
        pending: L'entite PendingValidation a traiter
        service: Le ValidationService pour les recherches

    Returns:
        - ID du candidat selectionne si validation
        - None si skip
        - "trash" si mise en corbeille
        - "quit" si abandon
    """
    # Parser les candidats initiaux
    candidates = _parse_candidates_to_search_results(pending.candidates)
    paginator = CandidatePaginator(candidates)
    # Cache des details par page pour eviter les appels API redondants
    details_cache: dict[int, dict[str, MediaDetails]] = {}
    # Flag pour eviter de reafficher les candidats apres certaines commandes
    should_redisplay = True

    while True:
        # Afficher les candidats avec details enrichis (sauf si juste un prompt)
        if should_redisplay:
            if paginator.candidates:
                # Recuperer les details pour la page courante (avec cache)
                page_key = paginator.current_page
                if page_key not in details_cache:
                    console.print("[dim]Chargement des details...[/dim]")
                    details_cache[page_key] = await _fetch_details_for_page(
                        paginator, service
                    )
                details_map = details_cache[page_key]

                display_enriched_candidates(paginator, pending, details_map)
            else:
                # Afficher le nom du fichier - utiliser le symlink en priorite
                filename = get_display_filename(pending)
                console.print(f"\n[bold cyan]Fichier:[/bold cyan] {filename}")
                console.print("[yellow]Aucun candidat disponible[/yellow]")

        # Remettre le flag par defaut pour la prochaine iteration
        should_redisplay = True

        # Demander le choix avec les options principales visibles
        console.print(
            "[dim]Options: [cyan]1-5[/cyan]=selectionner  "
            "[cyan]s[/cyan]=skip  [cyan]v[/cyan]=voir  [cyan]y[/cyan]=youtube  "
            "[cyan]a[/cyan]=analyser  [cyan]?[/cyan]=aide[/dim]"
        )
        choice = Prompt.ask("[bold]Choix[/bold]", default="1")
        choice = choice.strip().lower()

        # Selection par numero
        if choice.isdigit():
            num = int(choice)
            if 1 <= num <= len(paginator.current_items):
                candidate = paginator.select(num)
                if candidate:
                    # Afficher mini-recap
                    year_str = f" ({candidate.year})" if candidate.year else ""
                    console.print(
                        f"[bold]Selection:[/bold] {candidate.title}{year_str}"
                    )

                    if Confirm.ask("Valider ?", default=True):
                        return candidate.id
            else:
                console.print("[red]Numero invalide[/red]")

        # Skip
        elif choice == "s":
            return None

        # Trash
        elif choice == "t":
            return "trash"

        # Recherche manuelle
        elif choice == "r":
            query = Prompt.ask("[bold]Recherche[/bold]")
            if query.strip():
                # Detecter automatiquement si c'est une serie
                is_series = determine_is_series(pending)
                console.print(
                    f"[dim]Recherche {'serie' if is_series else 'film'}...[/dim]"
                )

                results = await service.search_manual(query, is_series=is_series)
                if results:
                    paginator = CandidatePaginator(results)
                    # Reinitialiser le cache des details pour les nouveaux candidats
                    details_cache.clear()
                    console.print(f"[green]{len(results)} resultat(s) trouve(s)[/green]")
                else:
                    console.print("[yellow]Aucun resultat[/yellow]")

        # ID externe
        elif choice == "i":
            id_input = Prompt.ask("[bold]ID externe[/bold]")
            id_type, id_value = detect_external_id(id_input)

            if id_type == "numeric":
                # Demander la source pour un ID numerique
                source = Prompt.ask(
                    "Source", choices=["tmdb", "tvdb"], default="tmdb"
                )
                id_type = source

            if id_type and id_value:
                console.print(f"[dim]Recherche {id_type.upper()} ID {id_value}...[/dim]")
                details = await service.search_by_external_id(id_type, id_value)

                if details:
                    # Afficher les details et demander confirmation
                    year_str = f" ({details.year})" if details.year else ""
                    console.print(f"[bold]Trouve:[/bold] {details.title}{year_str}")

                    if details.genres:
                        console.print(f"[dim]Genres: {', '.join(details.genres)}[/dim]")

                    if Confirm.ask("Valider ?", default=True):
                        return details.id
                else:
                    console.print("[yellow]Non trouve[/yellow]")
            else:
                console.print(
                    "[yellow]Format non reconnu. Utilisez ttXXXXXXX (IMDB) ou "
                    "un ID numerique[/yellow]"
                )

        # Page suivante
        elif choice == "n":
            if paginator.has_more():
                paginator.next_page()
            else:
                console.print("[yellow]Pas d'autres pages[/yellow]")

        # Visionner le fichier
        elif choice == "v":
            if pending.video_file and pending.video_file.path:
                import subprocess
                import sys
                file_path = str(pending.video_file.path)
                console.print(f"[dim]Ouverture de {file_path}...[/dim]")
                try:
                    if sys.platform == "linux":
                        subprocess.Popen(["xdg-open", file_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    elif sys.platform == "darwin":
                        subprocess.Popen(["open", file_path])
                    else:
                        subprocess.Popen(["start", file_path], shell=True)
                except Exception as e:
                    console.print(f"[red]Erreur: {e}[/red]")
            else:
                console.print("[yellow]Chemin du fichier non disponible[/yellow]")
            should_redisplay = False

        # Ouvrir YouTube pour le trailer d'un candidat
        elif choice.startswith("y"):
            # y ou y1, y2, etc.
            import urllib.parse
            import webbrowser
            num = 1
            if len(choice) > 1 and choice[1:].isdigit():
                num = int(choice[1:])
            if 1 <= num <= len(paginator.current_items):
                candidate = paginator.current_items[num - 1]
                year_str = f" {candidate.year}" if candidate.year else ""
                query = f"{candidate.title}{year_str} trailer"
                url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
                console.print(f"[dim]Recherche YouTube: {query}[/dim]")
                webbrowser.open(url)
            else:
                console.print("[yellow]Numero invalide[/yellow]")
            should_redisplay = False

        # Analyser le generique avec IA/OCR
        elif choice == "a":
            if not pending.video_file or not pending.video_file.path:
                console.print("[yellow]Chemin du fichier non disponible[/yellow]")
            elif not paginator.candidates:
                console.print("[yellow]Aucun candidat a comparer[/yellow]")
            else:
                from src.services.credits_analyzer import CreditsAnalyzer
                import os

                # Recuperer la cle API depuis l'environnement
                api_key = os.environ.get("ANTHROPIC_API_KEY")
                analyzer = CreditsAnalyzer(anthropic_api_key=api_key)

                available, msg = analyzer.is_available()
                if not available:
                    console.print(f"[red]Analyse non disponible: {msg}[/red]")
                else:
                    console.print("[dim]Extraction du generique et analyse OCR...[/dim]")

                    # Analyser le generique
                    analysis = await analyzer.analyze(pending.video_file.path)

                    if not analysis.raw_text:
                        console.print("[yellow]Aucun texte detecte dans le generique[/yellow]")
                    else:
                        console.print(f"[dim]Methode: {analysis.method}, confiance OCR: {analysis.confidence:.0f}%[/dim]")

                        # Afficher un extrait du texte detecte pour diagnostic
                        preview = analysis.raw_text[:500].replace("\n", " ")
                        console.print(f"[dim]Texte: {preview}...[/dim]")

                        # Recuperer les details des candidats pour comparaison
                        candidates_details = []
                        for i, cand in enumerate(paginator.current_items):
                            # Recuperer les details depuis le cache ou l'API
                            page_key = paginator.current_page
                            if page_key in details_cache and cand.id in details_cache[page_key]:
                                details = details_cache[page_key][cand.id]
                                candidates_details.append({
                                    "id": cand.id,
                                    "title": cand.title,
                                    "year": cand.year,
                                    "director": details.director if details else None,
                                    "actors": details.cast[:5] if details and details.cast else [],
                                })

                        if candidates_details:
                            matches = analyzer.match_with_candidates(analysis, candidates_details)

                            if matches:
                                console.print("\n[bold]Correspondances trouvees:[/bold]")
                                for match in matches[:3]:
                                    year_str = f" ({match.candidate_year})" if match.candidate_year else ""
                                    console.print(
                                        f"  [green]{match.match_score:.0f}%[/green] {match.candidate_title}{year_str}"
                                    )
                                    if match.matched_director:
                                        console.print(f"       [dim]Realisateur: ✓[/dim]")
                                    if match.matched_actors:
                                        console.print(f"       [dim]Acteurs: {', '.join(match.matched_actors)}[/dim]")

                                # Proposer de valider le meilleur match
                                # Fiable si: 3+ acteurs, ou realisateur + 1 acteur, ou score >= 50
                                best = matches[0]
                                num_actors = len(best.matched_actors)
                                is_reliable = (
                                    num_actors >= 3 or
                                    (best.matched_director and num_actors >= 1) or
                                    best.match_score >= 50
                                )

                                if is_reliable:
                                    if Confirm.ask(
                                        f"\nValider [bold]{best.candidate_title}[/bold] ?",
                                        default=True
                                    ):
                                        return best.candidate_id
                            else:
                                console.print("[yellow]Aucune correspondance trouvee avec les candidats[/yellow]")
                        else:
                            console.print("[yellow]Details des candidats non disponibles[/yellow]")
            should_redisplay = False

        # Aide
        elif choice == "?":
            display_help()
            should_redisplay = False

        # Quitter
        elif choice == "q":
            return "quit"

        else:
            console.print("[yellow]Commande non reconnue. Tapez ? pour l'aide[/yellow]")


def _parse_candidates_to_search_results(candidates: list) -> list[SearchResult]:
    """
    Parse les candidats depuis leur forme stockee en SearchResult.

    Args:
        candidates: Liste de candidats (dict ou SearchResult)

    Returns:
        Liste de SearchResult
    """
    if not candidates:
        return []

    parsed = []
    for c in candidates:
        if isinstance(c, SearchResult):
            parsed.append(c)
        elif isinstance(c, dict):
            parsed.append(
                SearchResult(
                    id=c.get("id", ""),
                    title=c.get("title", ""),
                    year=c.get("year"),
                    score=c.get("score", 0.0),
                    source=c.get("source", ""),
                )
            )
    return parsed


class ConflictResolution(str):
    """Options de resolution de conflit."""

    KEEP_OLD = "old"
    KEEP_NEW = "new"
    KEEP_BOTH = "both"
    SKIP = "skip"


def format_file_size(size_bytes: int) -> str:
    """Formate une taille en octets en format lisible."""
    if size_bytes >= 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} Go"
    elif size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.0f} Mo"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.0f} Ko"
    return f"{size_bytes} o"


def format_duration(seconds: int | None) -> str:
    """Formate une duree en secondes en format HH:MM:SS."""
    if seconds is None:
        return "?"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    return f"{minutes}m{secs:02d}s"


def display_similar_content_conflict(
    similar_info: "SimilarContentInfo",
    new_file_info: "ExistingFileInfo | None",
    new_file_count: int = 1,
) -> None:
    """
    Affiche un conflit de contenu similaire pour decision utilisateur.

    Args:
        similar_info: Information sur le contenu similaire existant
        new_file_info: Information sur le nouveau fichier (si disponible)
        new_file_count: Nombre de nouveaux fichiers (pour les series)
    """
    console.print("\n[bold yellow]⚠ Contenu similaire detecte[/bold yellow]\n")
    console.print(f"[dim]{similar_info.similarity_reason}[/dim]\n")

    # Tableau comparatif
    table = Table(
        title="Comparaison", show_header=True, header_style="bold cyan"
    )
    table.add_column("", style="dim")
    table.add_column(f"[red]Existant[/red]\n{similar_info.existing_title}", justify="center")
    table.add_column(f"[green]Nouveau[/green]\n{similar_info.new_title}", justify="center")

    # Collecter les infos existantes
    existing_files = similar_info.existing_files
    total_existing_size = sum(f.size_bytes for f in existing_files)
    existing_resolutions = set(f.resolution for f in existing_files if f.resolution)
    existing_codecs = set(f.video_codec for f in existing_files if f.video_codec)
    existing_audio = set(f.audio_codec for f in existing_files if f.audio_codec)

    # Infos du nouveau fichier
    new_size = format_file_size(new_file_info.size_bytes) if new_file_info else "?"
    new_resolution = new_file_info.resolution if new_file_info else "?"
    new_video_codec = new_file_info.video_codec if new_file_info else "?"
    new_audio_codec = new_file_info.audio_codec if new_file_info else "?"

    # Ajouter les lignes
    table.add_row(
        "Fichiers",
        str(len(existing_files)),
        str(new_file_count),
    )
    table.add_row(
        "Taille totale",
        format_file_size(total_existing_size),
        new_size,
    )
    table.add_row(
        "Resolution",
        ", ".join(sorted(existing_resolutions)) or "?",
        new_resolution or "?",
    )
    table.add_row(
        "Codec video",
        ", ".join(sorted(existing_codecs)) or "?",
        new_video_codec or "?",
    )
    table.add_row(
        "Codec audio",
        ", ".join(sorted(existing_audio)) or "?",
        new_audio_codec or "?",
    )

    console.print(table)


def prompt_conflict_resolution() -> str:
    """
    Demande a l'utilisateur de choisir la resolution du conflit.

    Returns:
        "old", "new", "both" ou "skip"
    """
    console.print("\n[bold]Options:[/bold]")
    console.print("  [cyan]1[/cyan] Garder l'[red]ancien[/red] (deplacer le nouveau vers la zone d'attente)")
    console.print("  [cyan]2[/cyan] Garder le [green]nouveau[/green] (deplacer l'ancien vers la zone d'attente)")
    console.print("  [cyan]3[/cyan] Garder les [yellow]deux[/yellow] (creer un sous-dossier pour le nouveau)")
    console.print("  [cyan]s[/cyan] Passer (ne rien faire pour ce fichier)")

    choice = Prompt.ask(
        "[bold]Choix[/bold]",
        choices=["1", "2", "3", "s"],
        default="s",
    )

    if choice == "1":
        return ConflictResolution.KEEP_OLD
    elif choice == "2":
        return ConflictResolution.KEEP_NEW
    elif choice == "3":
        return ConflictResolution.KEEP_BOTH
    else:
        return ConflictResolution.SKIP


def display_batch_summary(transfers: list[dict]) -> None:
    """
    Affiche un resume des transferts prevus sous forme d'arborescence.

    Structure affichee:
    - Zone symlinks (video_dir)
      - Films ou Series groupes par type/lettre/titre
        - Fichier symlink -> [dim]cible stockage[/dim]

    Args:
        transfers: Liste de dicts avec keys 'source', 'destination', 'new_filename',
                   'symlink_destination', 'is_series', 'title', 'year'
    """
    if not transfers:
        console.print("[yellow]Aucun transfert a effectuer.[/yellow]")
        return

    # Extraire video_dir et storage_dir depuis les chemins
    first_symlink = transfers[0].get("symlink_destination")
    first_storage = transfers[0].get("destination")

    # Determiner les racines
    video_dir = None
    storage_dir = None
    if first_symlink:
        # Remonter pour trouver la racine video (avant Films/ ou Séries/)
        parts = first_symlink.parts
        for i, part in enumerate(parts):
            if part in ("Films", "Séries"):
                video_dir = first_symlink.parents[len(parts) - i - 1]
                break
    if first_storage:
        parts = first_storage.parts
        for i, part in enumerate(parts):
            if part in ("Films", "Séries"):
                storage_dir = first_storage.parents[len(parts) - i - 1]
                break

    # Separer films et series
    movies = [t for t in transfers if not t.get("is_series", False)]
    series = [t for t in transfers if t.get("is_series", False)]

    # Arbre principal (zone symlinks)
    tree = Tree(f"[bold blue]{video_dir or 'Symlinks'}[/bold blue]")

    # Branche Films
    if movies:
        films_branch = tree.add("[bold cyan]Films/[/bold cyan]")
        # Grouper par sous-repertoire (genre/lettre)
        movie_dirs: dict[str, list[dict]] = {}
        for m in movies:
            symlink_dest = m.get("symlink_destination")
            if symlink_dest and video_dir:
                try:
                    rel_path = symlink_dest.relative_to(video_dir)
                    # Prendre le chemin parent sans "Films/"
                    parent_parts = rel_path.parts[1:-1]  # Enlever Films/ et le fichier
                    parent = "/".join(parent_parts) if parent_parts else ""
                except ValueError:
                    parent = ""
            else:
                parent = ""
            if parent not in movie_dirs:
                movie_dirs[parent] = []
            movie_dirs[parent].append(m)

        for dir_path in sorted(movie_dirs.keys()):
            if dir_path:
                dir_branch = films_branch.add(f"[cyan]{dir_path}/[/cyan]")
            else:
                dir_branch = films_branch
            for m in movie_dirs[dir_path]:
                new_name = m["new_filename"]
                storage_dest = m.get("destination")
                if storage_dest and storage_dir:
                    try:
                        rel_storage = storage_dest.relative_to(storage_dir)
                        storage_str = f" [dim]-> {rel_storage}[/dim]"
                    except ValueError:
                        storage_str = f" [dim]-> {storage_dest}[/dim]"
                else:
                    storage_str = ""
                dir_branch.add(f"[green]{new_name}[/green]{storage_str}")

    # Branche Series
    if series:
        # Grouper par type, lettre, serie, saison
        type_groups: dict[str, dict[str, dict[str, dict[str, list[dict]]]]] = {}

        for s in series:
            symlink_dest = s.get("symlink_destination")
            series_type = "Séries TV"
            letter = "?"

            if symlink_dest and video_dir:
                try:
                    rel_path = symlink_dest.relative_to(video_dir)
                    parts = rel_path.parts
                    # Structure: Séries/{Type}/{Lettre}/{Titre}/{Saison}/fichier
                    if len(parts) >= 5:
                        series_type = parts[1]
                        letter = parts[2]
                except ValueError:
                    pass

            title = s.get("title", "Inconnu")
            year = s.get("year", "")
            series_key = f"{title} ({year})" if year else title
            season_dir = symlink_dest.parent.name if symlink_dest else "Saison ??"

            if series_type not in type_groups:
                type_groups[series_type] = {}
            if letter not in type_groups[series_type]:
                type_groups[series_type][letter] = {}
            if series_key not in type_groups[series_type][letter]:
                type_groups[series_type][letter][series_key] = {}
            if season_dir not in type_groups[series_type][letter][series_key]:
                type_groups[series_type][letter][series_key][season_dir] = []
            type_groups[series_type][letter][series_key][season_dir].append(s)

        # Afficher l'arbre des series
        for series_type in sorted(type_groups.keys()):
            type_branch = tree.add(f"[bold magenta]Séries/{series_type}/[/bold magenta]")

            for letter in sorted(type_groups[series_type].keys()):
                letter_branch = type_branch.add(f"[magenta]{letter}/[/magenta]")

                for series_name in sorted(type_groups[series_type][letter].keys()):
                    series_branch = letter_branch.add(f"[magenta]{series_name}/[/magenta]")

                    for season in sorted(type_groups[series_type][letter][series_name].keys()):
                        season_branch = series_branch.add(f"[dim]{season}/[/dim]")
                        episodes = type_groups[series_type][letter][series_name][season]
                        episodes.sort(key=lambda e: e["new_filename"])

                        for ep in episodes:
                            new_name = ep["new_filename"]
                            storage_dest = ep.get("destination")
                            if storage_dest and storage_dir:
                                try:
                                    rel_storage = storage_dest.relative_to(storage_dir)
                                    storage_str = f" [dim]-> {rel_storage}[/dim]"
                                except ValueError:
                                    storage_str = f" [dim]-> {storage_dest}[/dim]"
                            else:
                                storage_str = ""
                            season_branch.add(f"[green]{new_name}[/green]{storage_str}")

    console.print(tree)


async def execute_batch_transfer(
    transfers: list[dict], transferer
) -> list[dict]:
    """
    Execute les transferts avec barre de progression.

    Signature transferer.transfer_file(source, destination, create_symlink=True) -> TransferResult

    Args:
        transfers: Liste de dicts avec keys 'source', 'destination'
        transferer: TransfererService injecte

    Returns:
        Liste de dicts {'success': bool, 'filename': str, 'error': str | None}
    """
    results = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Transfert...", total=len(transfers))

        for transfer in transfers:
            source = transfer["source"]
            destination = transfer["destination"]
            filename = source.name if hasattr(source, "name") else str(source)

            progress.update(task, description=f"[cyan]{filename}[/cyan]")

            # Appel transferer.transfer_file(source, destination, create_symlink=True)
            # Retourne TransferResult avec .success, .error, .conflict
            symlink_dest = transfer.get("symlink_destination")
            result: "TransferResult" = transferer.transfer_file(
                source=source,
                destination=destination,
                create_symlink=True,
                symlink_destination=symlink_dest,
            )

            if result.success:
                results.append({"success": True, "filename": filename, "error": None})
            else:
                error_msg = result.error or (
                    str(result.conflict) if result.conflict else "Erreur inconnue"
                )
                results.append({"success": False, "filename": filename, "error": error_msg})

            progress.advance(task)

    return results
