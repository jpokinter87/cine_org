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

from src.core.entities.video import PendingValidation
from src.core.ports.api_clients import SearchResult

if TYPE_CHECKING:
    from src.services.transferer import TransferResult
    from src.services.validation import ValidationService


# Console globale pour tous les affichages
console = Console()

# Nombre de candidats par page
PAGE_SIZE = 5

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
    Cree un panel Rich representant une carte de candidat.

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


def display_candidates(
    paginator: CandidatePaginator, pending: PendingValidation
) -> None:
    """
    Affiche les candidats de la page courante.

    Args:
        paginator: Paginateur avec les candidats
        pending: Entite PendingValidation pour afficher le nom du fichier
    """
    # Header avec nom du fichier
    filename = pending.video_file.filename if pending.video_file else "Fichier inconnu"
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


def display_help() -> None:
    """Affiche l'aide des commandes disponibles."""
    help_text = """
[bold]Commandes disponibles:[/bold]
  [cyan][1-5][/cyan]  Selectionner un candidat par son numero
  [cyan]s[/cyan]      Passer ce fichier (skip)
  [cyan]t[/cyan]      Mettre en corbeille (trash)
  [cyan]r[/cyan]      Recherche manuelle par titre
  [cyan]i[/cyan]      Saisir un ID externe (IMDB, TMDB, TVDB)
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
    if pending.video_file and pending.video_file.filename:
        filename = pending.video_file.filename
        for pattern in SERIES_PATTERNS:
            if pattern.search(filename):
                return True

    # Par defaut -> film
    return False


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

    while True:
        # Afficher les candidats
        if paginator.candidates:
            display_candidates(paginator, pending)
        else:
            filename = (
                pending.video_file.filename if pending.video_file else "Fichier inconnu"
            )
            console.print(f"\n[bold cyan]Fichier:[/bold cyan] {filename}")
            console.print("[yellow]Aucun candidat disponible[/yellow]")

        # Demander le choix
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

        # Aide
        elif choice == "?":
            display_help()

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


def display_batch_summary(transfers: list[dict]) -> None:
    """
    Affiche un resume des transferts prevus sous forme de tableau.

    Args:
        transfers: Liste de dicts avec keys 'source', 'destination', 'new_filename', 'action'
    """
    table = Table(
        title="Transferts a effectuer", show_header=True, header_style="bold magenta"
    )
    table.add_column("#", style="dim", width=4)
    table.add_column("Fichier source", style="cyan", no_wrap=True)
    table.add_column("Destination", style="green")
    table.add_column("Action", style="yellow")

    for idx, transfer in enumerate(transfers, start=1):
        source = transfer.get("source")
        source_name = source.name if hasattr(source, "name") else str(source)
        dest_str = str(transfer.get("destination", ""))
        action = transfer.get("action", "move+symlink")
        table.add_row(str(idx), source_name, dest_str, action)

    console.print(table)


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
