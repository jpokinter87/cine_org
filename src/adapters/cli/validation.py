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
from src.core.ports.api_clients import SearchResult

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
