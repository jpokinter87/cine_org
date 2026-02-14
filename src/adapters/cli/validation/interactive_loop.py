"""
Boucle interactive de validation et fonctions associees.

Fournit la boucle principale de validation, la detection d'IDs externes,
et la determination du type de media (film/serie).
"""

import re
from typing import TYPE_CHECKING

from guessit import guessit
from rich.prompt import Confirm, Prompt

from src.core.entities.video import PendingValidation
from src.core.ports.api_clients import MediaDetails, SearchResult
from src.services.matcher import MatcherService
from src.utils.helpers import parse_candidates

from .candidate_display import (
    CandidatePaginator,
    display_enriched_candidates,
    display_help,
)

if TYPE_CHECKING:
    from src.services.validation import ValidationService

# Pattern pour detecter un ID IMDB (tt suivi de 7-8 chiffres)
IMDB_PATTERN = re.compile(r"^tt\d{7,8}$", re.IGNORECASE)

# Pattern pour detecter les series dans les noms de fichiers (SxxExx, saison, season, episode)
SERIES_PATTERNS = [
    re.compile(r"[Ss]\d{1,2}[Ee]\d{1,2}"),  # S01E01, s1e1
    re.compile(r"[Ss]aison[\s._]*\d+", re.IGNORECASE),  # Saison 1, saison.1, saison_1
    re.compile(r"[Ss]eason[\s._]*\d+", re.IGNORECASE),  # Season 1, season.1
    re.compile(r"[Ee]pisode[\s._]*\d+", re.IGNORECASE),  # Episode 1, episode.1
    re.compile(r"\b\d{1,2}x\d{1,2}\b"),  # 1x01, 01x01
]


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


def _parse_candidates_to_search_results(candidates: list) -> list[SearchResult]:
    """Parse les candidats depuis leur forme stockee en SearchResult."""
    return parse_candidates(candidates)


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
) -> SearchResult | str | None:
    """
    Boucle interactive de validation pour un fichier.

    Args:
        pending: L'entite PendingValidation a traiter
        service: Le ValidationService pour les recherches

    Returns:
        - SearchResult du candidat selectionne si validation
        - None si skip
        - "trash" si mise en corbeille
        - "quit" si abandon
    """
    from . import console

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
                filename = (
                    pending.video_file.filename if pending.video_file else "Fichier inconnu"
                )
                console.print(f"\n[bold cyan]Fichier:[/bold cyan] {filename}")
                console.print("[yellow]Aucun candidat disponible[/yellow]")

        # Remettre le flag par defaut pour la prochaine iteration
        should_redisplay = True

        # Demander le choix avec les options principales visibles
        console.print(
            "[dim]Options: [cyan]1-5[/cyan]=selectionner  "
            "[cyan]r[/cyan]=recherche  [cyan]i[/cyan]=ID  "
            "[cyan]s[/cyan]=skip  [cyan]v[/cyan]=voir  [cyan]y[/cyan]=youtube  "
            "[cyan]a[/cyan]=analyser  [cyan]?[/cyan]=aide[/dim]"
        )
        # Default "r" si aucun candidat, sinon "1"
        default_choice = "1" if paginator.candidates else "r"
        choice = Prompt.ask("[bold]Choix[/bold]", default=default_choice)
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
                        return candidate
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
                    # Recalculer les scores bases sur le fichier original
                    matcher = MatcherService()
                    video = pending.video_file
                    # Extraire titre et annee du nom de fichier avec guessit
                    parsed = guessit(video.filename or "")
                    query_title = parsed.get("title", video.filename or "")
                    query_year = parsed.get("year")
                    query_duration = (
                        video.media_info.duration_seconds if video.media_info else None
                    )

                    scored_results = matcher.score_results(
                        results,
                        query_title=query_title,
                        query_year=query_year,
                        query_duration=query_duration,
                        is_series=is_series,
                    )

                    paginator = CandidatePaginator(scored_results)
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
                        # Creer un SearchResult pour le candidat selectionne par ID
                        return SearchResult(
                            id=id_value,
                            title=details.title,
                            year=details.year,
                            score=100.0,  # Score maximal car selection manuelle directe
                            source=id_type,  # "tmdb" ou "tvdb"
                        )
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

                        # Recuperer les details de TOUS les candidats pour comparaison
                        candidates_details = []
                        console.print("[dim]Chargement des details de tous les candidats...[/dim]")
                        for cand in paginator.candidates[:15]:  # Max 15 pour limiter les appels API
                            try:
                                details = await service._get_details_from_source(
                                    cand.source, cand.id
                                )
                                if details:
                                    candidates_details.append({
                                        "id": cand.id,
                                        "title": cand.title,
                                        "year": cand.year,
                                        "director": details.director if details else None,
                                        "actors": details.cast[:5] if details and details.cast else [],
                                    })
                            except Exception:
                                pass

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
                                        # Trouver le SearchResult correspondant
                                        for cand in paginator.candidates:
                                            if cand.id == best.candidate_id:
                                                return cand
                                        # Fallback: creer un SearchResult
                                        return SearchResult(
                                            id=best.candidate_id,
                                            title=best.candidate_title,
                                            year=best.candidate_year,
                                            score=best.match_score,
                                            source="tmdb",
                                        )
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
