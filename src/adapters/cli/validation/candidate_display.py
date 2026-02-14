"""
Affichage des candidats de validation avec Rich.

Fournit le paginateur, les fonctions de rendu des cartes candidat
(simples et enrichies), et les fonctions d'affichage.
"""

from typing import TYPE_CHECKING

from rich.panel import Panel

from src.core.entities.video import PendingValidation
from src.core.ports.api_clients import SearchResult

if TYPE_CHECKING:
    from src.core.ports.api_clients import MediaDetails

# Nombre de candidats par page
PAGE_SIZE = 5


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
    from . import console

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
    from . import console

    from src.core.ports.api_clients import MediaDetails

    # Header avec nom du fichier
    filename = pending.video_file.filename if pending.video_file else "Fichier inconnu"
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
    from . import console

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
