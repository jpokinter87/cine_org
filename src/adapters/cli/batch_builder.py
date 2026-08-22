"""
Construction de la liste des transferts pour le batch.

Ce module fournit les fonctions pour construire la liste des transferts
a partir des fichiers valides, en generant les noms et chemins de destination.

Responsabilites:
- Construction des donnees de transfert pour les films
- Construction des donnees de transfert pour les series
- Enrichissement des metadonnees (genres, notes, etc.) depuis les API
"""

import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from loguru import logger
from rich.console import Console

from src.adapters.cli.helpers import (
    _extract_language_from_filename,
    _extract_part_from_filename,
    _extract_episode_end,
    _extract_series_info,
    _extract_subtitle_language_from_filename,
    _looks_like_episode,
)

if TYPE_CHECKING:
    from src.container import Container
    from src.core.entities.media import Episode, Movie, Series
    from src.core.entities.video import PendingValidation
    from src.core.ports.api_clients import MediaDetails


console = Console()


def _extract_tech_from_media_info(
    media_info,
    video_file=None,
) -> tuple[str | None, str | None, str | None, tuple[str, ...], int | None]:
    """
    Extrait les metadonnees techniques depuis MediaInfo.

    Returns:
        Tuple (codec_video, codec_audio, resolution, languages, file_size_bytes)
    """
    if not media_info:
        return None, None, None, (), video_file.size_bytes if video_file else None

    codec_video = media_info.video_codec.name if media_info.video_codec else None
    codec_audio = media_info.audio_codecs[0].name if media_info.audio_codecs else None
    resolution = (
        f"{media_info.resolution.width}x{media_info.resolution.height}"
        if media_info.resolution
        else None
    )
    languages = (
        tuple(lang.code for lang in media_info.audio_languages)
        if media_info.audio_languages
        else ()
    )
    file_size_bytes = video_file.size_bytes if video_file else None

    return codec_video, codec_audio, resolution, languages, file_size_bytes


class TransferData:
    """
    Donnees de transfert pour un fichier.

    Attributs:
        pending: PendingValidation source
        source: Path du fichier source
        destination: Path de destination (stockage)
        new_filename: Nom du fichier renomme
        symlink_destination: Path du symlink (optionnel)
        is_series: True si c'est une serie
        title: Titre du media
        year: Annee du media
    """

    def __init__(
        self,
        pending: "PendingValidation",
        source: Path,
        destination: Path,
        new_filename: str,
        symlink_destination: Path | None = None,
        is_series: bool = False,
        title: str = "",
        year: int | None = None,
    ):
        self.pending = pending
        self.source = source
        self.destination = destination
        self.new_filename = new_filename
        self.symlink_destination = symlink_destination
        self.is_series = is_series
        self.title = title
        self.year = year

    def to_dict(self) -> dict:
        """Convertit en dict pour compatibilite avec le code existant."""
        data = {
            "pending": self.pending,
            "source": self.source,
            "destination": self.destination,
            "new_filename": self.new_filename,
            "action": "move+symlink",
            "is_series": self.is_series,
            "title": self.title,
            "year": self.year,
        }
        if self.symlink_destination:
            data["symlink_destination"] = self.symlink_destination
        return data


async def resolve_media_type(
    candidate_source: str,
    candidate_id: str,
    filename: str,
    tmdb_client,
) -> Optional[tuple[bool, str, str]]:
    """
    Determine le type du media a partir du FICHIER, pas de la seule source API.

    La source ``tmdb_tv`` est ambigue : elle designe une serie TMDB, mais elle
    sert aussi aux **films** classes en serie sur TMDB (cas « Tout le bleu du
    ciel »), ou l'entree film est le bon rangement. Se fier a la source seule
    faisait basculer en film tout episode valide via l'onglet ID IMDB.

    Quand le fichier est formellement un episode, le tvdb_id du candidat est
    resolu pour que tout l'aval (episodes, completude) reste sur TVDB par ID.
    Une resolution impossible est bloquante : ranger un episode en film cree
    une entree fantome difficile a rattraper.

    Args:
        candidate_source: Source du candidat valide ("tvdb", "tmdb_tv", "tmdb")
        candidate_id: Identifiant du candidat dans sa source
        filename: Nom du fichier a transferer
        tmdb_client: Client TMDB (pour la resolution du tvdb_id)

    Returns:
        Tuple (is_series, source, id) a utiliser en aval, ou None si le type
        ne peut pas etre determine sans risque d'erreur de rangement.
    """
    if candidate_source == "tvdb":
        return True, candidate_source, candidate_id

    if candidate_source != "tmdb_tv" or not _looks_like_episode(filename):
        if candidate_source == "tmdb" and _looks_like_episode(filename):
            logger.warning(
                "Fichier reconnu episode mais candidat film TMDB retenu : {}",
                filename,
            )
        return False, candidate_source, candidate_id

    if not tmdb_client or not getattr(tmdb_client, "_api_key", None):
        logger.warning(
            "Client TMDB indisponible : tvdb_id irrecuperable pour {}", filename
        )
        return None

    try:
        external_ids = await tmdb_client.get_tv_external_ids(candidate_id)
    except Exception as e:
        logger.warning(
            f"Erreur external_ids TMDB pour {filename} ({candidate_id}): {e}"
        )
        return None

    tvdb_id = external_ids.get("tvdb_id") if external_ids else None
    if not tvdb_id:
        logger.warning(
            "Serie TMDB {} sans tvdb_id : {} ne peut pas etre range",
            candidate_id,
            filename,
        )
        return None

    return True, "tvdb", str(tvdb_id)


async def _enrich_movie_metadata(
    movie_id: str,
    tmdb_client,
    container: "Container",
    source: str = "tmdb",
) -> tuple[
    tuple[str, ...], "MediaDetails | None", str | None, float | None, int | None
]:
    """
    Enrichit les metadonnees d'un film depuis TMDB.

    Args:
        movie_id: ID TMDB du film
        tmdb_client: Client TMDB
        container: Container pour acceder au repo IMDb
        source: Source du candidat ("tmdb" ou "tmdb_tv" pour les séries TV TMDB)

    Returns:
        Tuple (genres, details, imdb_id, imdb_rating, imdb_votes)
    """
    movie_genres: tuple[str, ...] = ()
    movie_details = None
    imdb_id = None
    imdb_rating = None
    imdb_votes = None

    if tmdb_client and getattr(tmdb_client, "_api_key", None) and movie_id:
        try:
            if source == "tmdb_tv":
                movie_details = await tmdb_client.get_tv_details(movie_id)
            else:
                movie_details = await tmdb_client.get_details(movie_id)
            if movie_details and movie_details.genres:
                movie_genres = movie_details.genres

            # Recuperer l'imdb_id via external_ids
            if source == "tmdb_tv":
                external_ids = await tmdb_client.get_tv_external_ids(movie_id)
            else:
                external_ids = await tmdb_client.get_external_ids(movie_id)
            if external_ids:
                imdb_id = external_ids.get("imdb_id")

            # Recuperer la note IMDb depuis le cache local
            if imdb_id:
                from src.adapters.imdb.dataset_importer import IMDbDatasetImporter

                cache_dir = Path(".cache/imdb")
                imdb_session = container.session()
                imdb_importer = IMDbDatasetImporter(
                    cache_dir=cache_dir, session=imdb_session
                )
                rating_data = imdb_importer.get_rating(imdb_id)
                if rating_data:
                    imdb_rating, imdb_votes = rating_data

        except Exception:
            pass  # Garder les valeurs par defaut en cas d'erreur

    return movie_genres, movie_details, imdb_id, imdb_rating, imdb_votes


async def _enrich_series_metadata(
    title: str,
    year: int | None,
    tmdb_client,
    container: "Container",
) -> tuple[
    int | None,
    float | None,
    int | None,
    str | None,
    float | None,
    int | None,
]:
    """
    Enrichit les notes d'une nouvelle serie depuis TMDB + cache IMDb local.

    Pont TVDB -> TMDB -> IMDb : la serie est matchee initialement via TVDB
    (qui n'expose pas de note), donc on cherche son equivalent TMDB pour
    recuperer vote_average + vote_count, puis on lit le cache IMDb local
    pour imdb_rating + imdb_votes.

    Args:
        title: Titre de la serie
        year: Annee de premiere diffusion (peut etre None)
        tmdb_client: Client TMDB
        container: Container DI (pour acceder a la session IMDb)

    Returns:
        Tuple (tmdb_id, vote_average, vote_count, imdb_id, imdb_rating, imdb_votes).
        Toute valeur indisponible vaut None — le workflow continue sans bloquer.
    """
    tmdb_id: int | None = None
    vote_average: float | None = None
    vote_count: int | None = None
    imdb_id: str | None = None
    imdb_rating: float | None = None
    imdb_votes: int | None = None

    if not (tmdb_client and getattr(tmdb_client, "_api_key", None)):
        return tmdb_id, vote_average, vote_count, imdb_id, imdb_rating, imdb_votes

    try:
        from src.services.series_enricher import pick_best_tv_match

        results = await tmdb_client.search_tv(title, year=year)
        if not results:
            return tmdb_id, vote_average, vote_count, imdb_id, imdb_rating, imdb_votes

        best = pick_best_tv_match(results, title, year)
        if not best:
            return tmdb_id, vote_average, vote_count, imdb_id, imdb_rating, imdb_votes

        details = await tmdb_client.get_tv_details(best.id)
        if details:
            try:
                tmdb_id = int(best.id)
            except (TypeError, ValueError):
                tmdb_id = None
            vote_average = details.vote_average
            vote_count = details.vote_count

        ext_ids = await tmdb_client.get_tv_external_ids(best.id)
        if ext_ids:
            imdb_id = ext_ids.get("imdb_id") or None

        if imdb_id:
            from src.adapters.imdb.dataset_importer import IMDbDatasetImporter

            imdb_session = container.session()
            imdb_importer = IMDbDatasetImporter(
                cache_dir=Path(".cache/imdb"), session=imdb_session
            )
            rating_data = imdb_importer.get_rating(imdb_id)
            if rating_data:
                imdb_rating, imdb_votes = rating_data

    except Exception:
        # Workflow resilient : un echec d'enrichissement ne bloque pas le transfert.
        pass

    return tmdb_id, vote_average, vote_count, imdb_id, imdb_rating, imdb_votes


def _build_movie_transfer_data(
    pending: "PendingValidation",
    candidate: dict | object,
    movie: "Movie",
    dest_dir: Path,
    symlink_dir: Path,
    new_filename: str,
) -> TransferData:
    """
    Construit les donnees de transfert pour un film.

    Args:
        pending: PendingValidation source
        candidate: Candidat selectionne (dict ou SearchResult)
        movie: Entite Movie avec toutes les metadonnees
        dest_dir: Repertoire de destination (stockage)
        symlink_dir: Repertoire du symlink
        new_filename: Nom du fichier renomme

    Returns:
        TransferData complet
    """
    source_path = (
        pending.video_file.path
        if pending.video_file and pending.video_file.path
        else None
    )

    return TransferData(
        pending=pending,
        source=source_path,
        destination=dest_dir / new_filename,
        new_filename=new_filename,
        symlink_destination=symlink_dir / new_filename,
        is_series=False,
        title=movie.title,
        year=movie.year,
    )


async def _build_series_transfer_data(
    pending: "PendingValidation",
    candidate: dict | object,
    renamer,
    organizer,
    storage_dir: Path,
    video_dir: Path,
) -> TransferData:
    """
    Construit les donnees de transfert pour une serie.

    Args:
        pending: PendingValidation source
        candidate: Candidat selectionne (dict ou SearchResult)
        renamer: RenamerService
        organizer: OrganizerService
        storage_dir: Repertoire de stockage
        video_dir: Repertoire video (symlinks)

    Returns:
        TransferData complet
    """
    # Extraire les infos du candidat
    if isinstance(candidate, dict):
        candidate_title = candidate.get("title", "")
        candidate_year = candidate.get("year")
        candidate_source = candidate.get("source", "")
        series_id = candidate.get("id", "")
    else:
        candidate_title = candidate.title
        candidate_year = candidate.year
        candidate_source = candidate.source
        series_id = candidate.id

    # Extraire l'extension et langue
    source_path = (
        pending.video_file.path
        if pending.video_file and pending.video_file.path
        else None
    )
    extension = source_path.suffix if source_path and source_path.suffix else ".mkv"
    media_info = pending.video_file.media_info if pending.video_file else None
    original_filename = pending.video_file.filename if pending.video_file else ""
    fallback_language = _extract_language_from_filename(original_filename)

    # Extraire saison/episode
    filename = pending.video_file.filename if pending.video_file else ""
    season_num, episode_num = _extract_series_info(filename)
    episode_end = _extract_episode_end(filename)

    # Construire les entites Series et Episode
    from src.core.entities.media import Series, Episode

    series = Series(
        title=candidate_title,
        year=candidate_year,
        genres=(),  # Genres recuperes plus tard si disponible
    )
    episode = Episode(
        season_number=season_num,
        episode_number=episode_num,
        episode_end=episode_end,
        title="",  # Titre d'episode recuperé plus tard
    )

    # Generer le nouveau nom et chemin de destination
    new_filename = renamer.generate_series_filename(
        series=series,
        episode=episode,
        media_info=media_info,
        extension=extension,
        fallback_language=fallback_language,
    )
    dest_dir = organizer.get_series_destination(
        series=series,
        season_number=season_num,
        storage_dir=storage_dir,
        video_dir=video_dir,
    )
    symlink_dir = organizer.get_series_video_destination(
        series=series,
        season_number=season_num,
        video_dir=video_dir,
    )

    return TransferData(
        pending=pending,
        source=source_path,
        destination=dest_dir / new_filename,
        new_filename=new_filename,
        symlink_destination=symlink_dir / new_filename,
        is_series=True,
        title=candidate_title,
        year=candidate_year,
    )


async def build_transfers_batch(
    validated_list: list["PendingValidation"],
    container: "Container",
    storage_dir: Path,
    video_dir: Path,
    on_progress: "Callable[[int, int, str], None] | None" = None,
) -> list[dict]:
    """
    Construit la liste des transferts pour les fichiers valides.

    Args:
        validated_list: Liste des fichiers valides (status=VALIDATED)
        container: Container d'injection de dependances
        storage_dir: Repertoire de stockage
        video_dir: Repertoire video (symlinks)

    Returns:
        Liste de dicts avec les donnees de transfert
    """
    # Recuperer les services necessaires
    renamer = container.renamer_service()
    organizer = container.organizer_service()
    tvdb_client = container.tvdb_client()
    tmdb_client = container.tmdb_client()

    # Instancier les repositories UNE SEULE FOIS hors de la boucle
    # pour eviter d'epuiser le pool de connexions SQLite
    movie_repo = container.movie_repository()
    series_repo = container.series_repository()
    episode_repo = container.episode_repository()

    transfers = []
    total = len(validated_list)

    for idx, pending in enumerate(validated_list):
        # Recuperer le candidat selectionne
        candidate = None
        for c in pending.candidates:
            c_id = c.id if hasattr(c, "id") else c.get("id", "")
            if c_id == pending.selected_candidate_id:
                candidate = c
                break

        if candidate is None:
            filename = pending.video_file.filename if pending.video_file else "?"
            console.print(f"[red]Erreur:[/red] Candidat non trouve pour {filename}")
            continue

        # Extraire les infos du candidat
        if isinstance(candidate, dict):
            candidate_title = candidate.get("title", "")
            candidate_year = candidate.get("year")
            candidate_source = candidate.get("source", "")
            candidate_id = candidate.get("id", "")
        else:
            candidate_title = candidate.title
            candidate_year = candidate.year
            candidate_source = candidate.source
            candidate_id = candidate.id

        # Filet de sécurité : titre vide → fallback sur le nom de fichier parsé
        if not candidate_title:
            original_filename = (
                pending.video_file.filename if pending.video_file else ""
            )
            if original_filename:
                from src.adapters.parsing.guessit_parser import GuessitFilenameParser

                _fallback_parser = GuessitFilenameParser()
                parsed = _fallback_parser.parse(original_filename)
                if parsed.title and parsed.title != "Unknown":
                    candidate_title = parsed.title
                    console.print(
                        f"  [yellow]⚠[/yellow] Titre candidat vide pour {original_filename}, "
                        f"fallback sur titre parsé : {candidate_title}"
                    )

        # Determiner si c'est une serie : le type se decide sur le fichier,
        # pas sur la seule source API (cf. resolve_media_type)
        filename = pending.video_file.filename if pending.video_file else ""
        resolved = await resolve_media_type(
            candidate_source, candidate_id, filename, tmdb_client
        )
        if resolved is None:
            console.print(
                f"[red]Erreur:[/red] {filename} est un épisode mais la série TMDB "
                f"{candidate_id} n'a pas d'équivalent TVDB — fichier ignoré "
                "(le ranger en film créerait une entrée erronée)."
            )
            continue
        is_series, candidate_source, candidate_id = resolved

        # Notifier la progression
        if on_progress:
            filename = pending.video_file.filename if pending.video_file else "?"
            on_progress(idx + 1, total, filename)

        # Verifier le chemin source
        source_path = (
            pending.video_file.path
            if pending.video_file and pending.video_file.path
            else None
        )
        if source_path is None:
            filename = pending.video_file.filename if pending.video_file else "?"
            console.print(f"[red]Erreur:[/red] Chemin source manquant pour {filename}")
            continue

        extension = source_path.suffix if source_path.suffix else ".mkv"
        media_info = pending.video_file.media_info if pending.video_file else None

        # Extraire la langue du nom de fichier (fallback)
        original_filename = pending.video_file.filename if pending.video_file else ""
        fallback_language = _extract_language_from_filename(original_filename)

        if is_series:
            # === TRAITEMENT DES SERIES ===
            season_num, episode_num = _extract_series_info(original_filename)
            episode_end = _extract_episode_end(original_filename)

            # Recuperer le titre d'episode et les genres depuis TVDB
            episode_title = ""
            series_genres: tuple[str, ...] = ()
            canonical_count: Optional[int] = None

            if tvdb_client and getattr(tvdb_client, "_api_key", None) and candidate_id:
                try:
                    # Recuperer les details de la serie (genres)
                    series_details = await tvdb_client.get_details(candidate_id)
                    if series_details and series_details.genres:
                        series_genres = series_details.genres

                    # Recuperer le titre d'episode
                    ep_details = await tvdb_client.get_episode_details(
                        candidate_id, season_num, episode_num
                    )
                    if ep_details and ep_details.title:
                        episode_title = ep_details.title

                    # Canonical count : pour marquer les episodes hors canon
                    # comme is_extra=True (phase 42-01).
                    canonical_count = await tvdb_client.get_season_episode_count(
                        candidate_id, season_num
                    )
                except Exception:
                    pass

            # Extraire les metadonnees techniques du fichier
            codec_video, codec_audio, resolution_str, languages, file_size_bytes = (
                _extract_tech_from_media_info(media_info, pending.video_file)
            )

            # Recuperer la serie existante (pour eviter de refaire l'enrichissement
            # TMDB+IMDb a chaque nouvel episode et pour preserver les notes deja
            # peuplees si la nouvelle requete TMDB echoue ou est ambigue).
            tvdb_id_int = int(candidate_id) if candidate_id else None
            existing_series = (
                series_repo.get_by_tvdb_id(tvdb_id_int) if tvdb_id_int else None
            )

            if existing_series and existing_series.vote_average is not None:
                # Notes deja peuplees pour cette serie : on ne re-interroge pas TMDB.
                s_tmdb_id = existing_series.tmdb_id
                s_vote_avg = existing_series.vote_average
                s_vote_count = existing_series.vote_count
                s_imdb_id = existing_series.imdb_id
                s_imdb_rating = existing_series.imdb_rating
                s_imdb_votes = existing_series.imdb_votes
            else:
                # Premiere apparition (ou serie sans notes) : pont TVDB -> TMDB -> IMDb.
                (
                    s_tmdb_id,
                    s_vote_avg,
                    s_vote_count,
                    s_imdb_id,
                    s_imdb_rating,
                    s_imdb_votes,
                ) = await _enrich_series_metadata(
                    title=candidate_title,
                    year=candidate_year,
                    tmdb_client=tmdb_client,
                    container=container,
                )
                # Conserver les valeurs preexistantes en cas d'echec de l'appel TMDB.
                if existing_series:
                    s_tmdb_id = s_tmdb_id or existing_series.tmdb_id
                    s_imdb_id = s_imdb_id or existing_series.imdb_id
                    s_imdb_rating = s_imdb_rating or existing_series.imdb_rating
                    s_imdb_votes = s_imdb_votes or existing_series.imdb_votes

            # Construire les entites Series et Episode
            from src.core.entities.media import Series, Episode

            series = Series(
                tvdb_id=tvdb_id_int,
                tmdb_id=s_tmdb_id,
                imdb_id=s_imdb_id,
                title=candidate_title,
                year=candidate_year,
                genres=series_genres,
                overview=series_details.overview if series_details else None,
                poster_path=series_details.poster_url if series_details else None,
                vote_average=s_vote_avg,
                vote_count=s_vote_count,
                imdb_rating=s_imdb_rating,
                imdb_votes=s_imdb_votes,
            )
            is_extra = (
                canonical_count is not None and episode_num > canonical_count
            )
            episode = Episode(
                season_number=season_num,
                episode_number=episode_num,
                episode_end=episode_end,
                title=episode_title,
                codec_video=codec_video,
                codec_audio=codec_audio,
                resolution=resolution_str,
                languages=languages,
                file_size_bytes=file_size_bytes,
                is_extra=is_extra,
            )

            new_filename = renamer.generate_series_filename(
                series=series,
                episode=episode,
                media_info=media_info,
                extension=extension,
                fallback_language=fallback_language,
            )
            dest_dir = organizer.get_series_destination(
                series=series,
                season_number=season_num,
                storage_dir=storage_dir,
                video_dir=video_dir,
            )
            symlink_dir = organizer.get_series_video_destination(
                series=series,
                season_number=season_num,
                video_dir=video_dir,
            )

            # Sauvegarder la serie en base (ou recuperer si existante)
            saved_series = series_repo.save(series)

            # Sauvegarder l'episode en base
            episode.series_id = saved_series.id
            # Verifier si l'episode existe deja
            existing_eps = episode_repo.get_by_series(
                saved_series.id, season=season_num, episode=episode_num
            )
            if existing_eps:
                episode.id = existing_eps[0].id
            saved_episode = episode_repo.save(episode)

            year_str = f" ({series.year})" if series.year else ""
            console.print(
                f"  [green]✓[/green] [bold]{series.title}[/bold]{year_str} "
                f"S{season_num:02d}E{episode_num:02d} sauvegardé"
            )

            transfer_data = {
                "pending": pending,
                "source": source_path,
                "destination": dest_dir / new_filename,
                "new_filename": new_filename,
                "action": "move+symlink",
                "symlink_destination": symlink_dir / new_filename,
                "is_series": True,
                "title": candidate_title,
                "year": candidate_year,
                "series_id": saved_series.id,
                "episode_id": saved_episode.id,
            }
            transfers.append(transfer_data)

        else:
            # === TRAITEMENT DES FILMS ===
            # Enrichir les metadonnees depuis TMDB
            (
                movie_genres,
                movie_details,
                imdb_id,
                imdb_rating,
                imdb_votes,
            ) = await _enrich_movie_metadata(
                str(candidate_id), tmdb_client, container, source=candidate_source
            )

            # Extraire les metadonnees techniques du fichier
            codec_video, codec_audio, resolution, languages, file_size_bytes = (
                _extract_tech_from_media_info(media_info, pending.video_file)
            )

            # Creer l'entite Movie complete
            from src.core.entities.media import Movie

            movie = Movie(
                tmdb_id=int(candidate_id) if candidate_id else None,
                imdb_id=imdb_id,
                title=candidate_title,
                original_title=movie_details.original_title if movie_details else None,
                year=candidate_year,
                genres=movie_genres,
                duration_seconds=movie_details.duration_seconds
                if movie_details
                else None,
                overview=movie_details.overview if movie_details else None,
                poster_path=movie_details.poster_url if movie_details else None,
                vote_average=movie_details.vote_average if movie_details else None,
                vote_count=movie_details.vote_count if movie_details else None,
                imdb_rating=imdb_rating,
                imdb_votes=imdb_votes,
                director=movie_details.director if movie_details else None,
                cast=movie_details.cast if movie_details else (),
                codec_video=codec_video,
                codec_audio=codec_audio,
                resolution=resolution,
                languages=languages,
                file_size_bytes=file_size_bytes,
            )

            # Sauvegarder le film dans la base de donnees
            saved_movie = movie_repo.save(movie)

            # Afficher le feedback de sauvegarde avec les notes
            year_str = f" ({movie.year})" if movie.year else ""
            tmdb_str = (
                f"TMDB: {movie.vote_average:.1f}/10"
                if movie.vote_average
                else "TMDB: -"
            )
            imdb_str = (
                f"IMDb: {movie.imdb_rating:.1f}/10" if movie.imdb_rating else "IMDb: -"
            )
            console.print(
                f"  [green]✓[/green] [bold]{movie.title}[/bold]{year_str} "
                f"sauvegardé - {tmdb_str}, {imdb_str}"
            )

            new_filename = renamer.generate_movie_filename(
                movie=movie,
                media_info=media_info,
                extension=extension,
                fallback_language=fallback_language,
            )
            dest_dir = organizer.get_movie_destination(
                movie=movie,
                storage_dir=storage_dir,
                video_dir=video_dir,
            )
            symlink_dir = organizer.get_movie_video_destination(
                movie=movie,
                video_dir=video_dir,
            )

            transfer_data = {
                "pending": pending,
                "source": source_path,
                "destination": dest_dir / new_filename,
                "new_filename": new_filename,
                "action": "move+symlink",
                "symlink_destination": symlink_dir / new_filename,
                "is_series": False,
                "title": candidate_title,
                "year": candidate_year,
                "movie_id": saved_movie.id,
            }
            transfers.append(transfer_data)

    # Filet de securite : detecter les fichiers avec le meme nom de destination
    # (typiquement un film decoupe par le rippeur dont les parts n'ont pas ete detectees)
    transfers = _fix_duplicate_filenames(transfers, renamer)

    # Detection de doublons pre-transfert : titres similaires existants dans video_dir
    transfers = _detect_duplicates(transfers, video_dir)

    return transfers


def _fix_duplicate_filenames(
    transfers: list[dict],
    renamer,
) -> list[dict]:
    """
    Detecte et corrige les noms de fichiers en doublon dans le batch.

    Quand deux fichiers obtiennent le meme nom de destination, c'est probablement
    un film decoupe par le rippeur en plusieurs parties. Le filet re-parse les
    noms originaux pour extraire le numero de partie et regenerer les noms.

    Args:
        transfers: Liste des transferts construits.
        renamer: RenamerService pour regenerer les noms.

    Returns:
        Liste corrigee (les doublons recoivent un suffixe "Partie N").
    """
    from collections import defaultdict

    # Grouper par nom de destination
    by_destination: dict[str, list[int]] = defaultdict(list)
    for idx, t in enumerate(transfers):
        dest = str(t.get("destination", ""))
        by_destination[dest].append(idx)

    # Traiter les groupes avec des doublons
    for dest, indices in by_destination.items():
        if len(indices) < 2:
            continue

        console.print(
            f"  [yellow]⚠[/yellow] {len(indices)} fichiers avec le meme nom de destination, "
            f"correction automatique..."
        )

        # Extraire les numeros de partie depuis les noms originaux
        parts_found: list[tuple[int, int | None]] = []  # (index, part_num)
        for idx in indices:
            t = transfers[idx]
            original_filename = ""
            pending = t.get("pending")
            if pending and pending.video_file:
                original_filename = pending.video_file.filename or ""
            part_num = _extract_part_from_filename(original_filename)
            parts_found.append((idx, part_num))

        # Si aucune part n'a ete trouvee, numerotation sequentielle
        if all(p is None for _, p in parts_found):
            for seq, (idx, _) in enumerate(parts_found, start=1):
                parts_found[seq - 1] = (idx, seq)

        # Regenerer les noms avec le numero de partie
        for idx, part_num in parts_found:
            if part_num is None:
                continue

            t = transfers[idx]
            pending = t.get("pending")
            source_path = t.get("source")
            extension = source_path.suffix if source_path else ".mkv"
            media_info = (
                pending.video_file.media_info
                if pending and pending.video_file
                else None
            )
            original_filename = ""
            if pending and pending.video_file:
                original_filename = pending.video_file.filename or ""
            fallback_language = _extract_language_from_filename(original_filename)
            fallback_subtitle_language = _extract_subtitle_language_from_filename(
                original_filename
            )

            if t.get("is_series"):
                # Reconstruire Series/Episode depuis les infos existantes
                from src.core.entities.media import Series, Episode

                season_num, episode_num = _extract_series_info(original_filename)
                series = Series(title=t.get("title", ""), year=t.get("year"))
                episode = Episode(
                    season_number=season_num,
                    episode_number=episode_num,
                    episode_end=_extract_episode_end(original_filename),
                    title="",
                )
                new_filename = renamer.generate_series_filename(
                    series=series,
                    episode=episode,
                    media_info=media_info,
                    extension=extension,
                    fallback_language=fallback_language,
                    fallback_subtitle_language=fallback_subtitle_language,
                    part=part_num,
                )
            else:
                from src.core.entities.media import Movie

                movie = Movie(title=t.get("title", ""), year=t.get("year"))
                new_filename = renamer.generate_movie_filename(
                    movie=movie,
                    media_info=media_info,
                    extension=extension,
                    fallback_language=fallback_language,
                    fallback_subtitle_language=fallback_subtitle_language,
                    part=part_num,
                )

            # Mettre a jour le transfert
            old_filename = t["new_filename"]
            dest_dir = t["destination"].parent
            t["new_filename"] = new_filename
            t["destination"] = dest_dir / new_filename
            if t.get("symlink_destination"):
                symlink_dir = t["symlink_destination"].parent
                t["symlink_destination"] = symlink_dir / new_filename

            console.print(f"    [green]✓[/green] {old_filename} → {new_filename}")

        # Annoter les parties d'un film multi-parties : la plus petite partie
        # reste primaire (porte la fiche Movie), les autres deviennent des
        # MoviePart (cf. transfer_step._update_file_paths).
        film_parts = [
            (idx, part_num)
            for idx, part_num in parts_found
            if part_num is not None and not transfers[idx].get("is_series")
        ]
        if len(film_parts) >= 2:
            primary_idx = min(film_parts, key=lambda p: p[1])[0]
            for idx, part_num in film_parts:
                if idx != primary_idx:
                    transfers[idx]["movie_part_number"] = part_num

    return transfers


def _detect_duplicates(
    transfers: list[dict],
    video_dir: Path,
) -> list[dict]:
    """
    Détecte les doublons pré-transfert pour chaque fichier du batch.

    Pour chaque transfert, vérifie si un titre similaire existe déjà
    dans video_dir. Si oui, enrichit le dict avec les données du doublon
    et le score de qualité comparatif.

    Args:
        transfers: Liste des transferts construits.
        video_dir: Répertoire racine des symlinks.

    Returns:
        Liste enrichie avec les clés 'has_duplicate' et 'duplicate_match'.
    """
    from src.services.duplicate_detector import DuplicateDetector
    from src.services.transferer import ExistingFileInfo

    detector = DuplicateDetector()

    # Détecter par titre unique (éviter de scanner N fois pour N épisodes d'une même série)
    seen_titles: dict[str, object] = {}

    for t in transfers:
        title = t.get("title", "")
        year = t.get("year")
        is_series = t.get("is_series", False)
        cache_key = f"{title}|{year}|{is_series}"

        if cache_key in seen_titles:
            match = seen_titles[cache_key]
        else:
            match = detector.detect_duplicate(
                title=title,
                year=year,
                video_dir=video_dir,
                is_series=is_series,
            )
            seen_titles[cache_key] = match

        if match is not None:
            # Séries : vérifier au niveau épisode, pas saison.
            # Un épisode manquant ajouté à une série existante n'est PAS un doublon.
            if is_series:
                new_fn = t.get("new_filename", "")
                ep_m = re.search(r"S(\d+)E(\d+)", new_fn, re.IGNORECASE)
                if ep_m:
                    new_ep_key = f"S{int(ep_m.group(1)):02d}E{int(ep_m.group(2)):02d}"
                    # Vérification par épisode exact (prioritaire)
                    if match.existing_episodes and new_ep_key not in match.existing_episodes:
                        t["has_duplicate"] = False
                        t["duplicate_match"] = None
                        continue
                    # Fallback : vérification par saison (si pas d'épisodes collectés)
                    if not match.existing_episodes and match.existing_seasons:
                        new_season = int(ep_m.group(1))
                        if new_season not in match.existing_seasons:
                            t["has_duplicate"] = False
                            t["duplicate_match"] = None
                            continue

            # Calculer le score de qualité comparatif
            source = t.get("source")
            new_info = None
            if source and source.exists():
                new_info = ExistingFileInfo(
                    path=source,
                    size_bytes=source.stat().st_size,
                )
                # Enrichir avec les métadonnées techniques si disponible
                pending = t.get("pending")
                if pending and pending.video_file and pending.video_file.media_info:
                    mi = pending.video_file.media_info
                    # Extraire débits vidéo et audio réels via pymediainfo
                    v_bitrate = None
                    a_bitrate = None
                    try:
                        from pymediainfo import MediaInfo as PyMediaInfo

                        parsed = PyMediaInfo.parse(str(source))
                        for track in parsed.tracks:
                            if track.track_type == "Video" and v_bitrate is None:
                                if track.bit_rate is not None:
                                    v_bitrate = int(float(track.bit_rate) / 1000)
                            elif track.track_type == "Audio" and a_bitrate is None:
                                if track.bit_rate is not None:
                                    a_bitrate = int(float(track.bit_rate) / 1000)
                    except Exception:
                        pass
                    new_info = ExistingFileInfo(
                        path=source,
                        size_bytes=source.stat().st_size,
                        resolution=mi.resolution.label if mi.resolution else None,
                        video_codec=mi.video_codec.name if mi.video_codec else None,
                        audio_codec=(
                            mi.audio_codecs[0].name if mi.audio_codecs else None
                        ),
                        duration_seconds=mi.duration_seconds,
                        video_bitrate_kbps=v_bitrate,
                        audio_bitrate_kbps=a_bitrate,
                    )

            if new_info:
                match.quality = detector.compare_quality(match.existing_files, new_info)

            t["has_duplicate"] = True
            t["duplicate_match"] = match
        else:
            t["has_duplicate"] = False
            t["duplicate_match"] = None

    return transfers
