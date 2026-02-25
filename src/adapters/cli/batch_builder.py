"""
Construction de la liste des transferts pour le batch.

Ce module fournit les fonctions pour construire la liste des transferts
a partir des fichiers valides, en generant les noms et chemins de destination.

Responsabilites:
- Construction des donnees de transfert pour les films
- Construction des donnees de transfert pour les series
- Enrichissement des metadonnees (genres, notes, etc.) depuis les API
"""

from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console

from src.adapters.cli.helpers import (
    _extract_language_from_filename,
    _extract_series_info,
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
    codec_audio = (
        media_info.audio_codecs[0].name if media_info.audio_codecs else None
    )
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


async def _enrich_movie_metadata(
    movie_id: str,
    tmdb_client,
    container: "Container",
) -> tuple[tuple[str, ...], "MediaDetails | None", str | None, float | None, int | None]:
    """
    Enrichit les metadonnees d'un film depuis TMDB.

    Args:
        movie_id: ID TMDB du film
        tmdb_client: Client TMDB
        container: Container pour acceder au repo IMDb

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
            movie_details = await tmdb_client.get_details(movie_id)
            if movie_details and movie_details.genres:
                movie_genres = movie_details.genres

            # Recuperer l'imdb_id via external_ids
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
        pending.video_file.path if pending.video_file and pending.video_file.path else None
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
        pending.video_file.path if pending.video_file and pending.video_file.path else None
    )
    extension = source_path.suffix if source_path and source_path.suffix else ".mkv"
    media_info = pending.video_file.media_info if pending.video_file else None
    original_filename = pending.video_file.filename if pending.video_file else ""
    fallback_language = _extract_language_from_filename(original_filename)

    # Extraire saison/episode
    filename = pending.video_file.filename if pending.video_file else ""
    season_num, episode_num = _extract_series_info(filename)

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

    transfers = []

    for pending in validated_list:
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

        # Determiner si c'est une serie
        is_series = candidate_source == "tvdb"

        # Verifier le chemin source
        source_path = (
            pending.video_file.path if pending.video_file and pending.video_file.path else None
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

            # Recuperer le titre d'episode et les genres depuis TVDB
            episode_title = ""
            series_genres: tuple[str, ...] = ()

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
                except Exception:
                    pass

            # Extraire les metadonnees techniques du fichier
            codec_video, codec_audio, resolution_str, languages, file_size_bytes = (
                _extract_tech_from_media_info(media_info, pending.video_file)
            )

            # Construire les entites Series et Episode
            from src.core.entities.media import Series, Episode

            series = Series(
                tvdb_id=int(candidate_id) if candidate_id else None,
                title=candidate_title,
                year=candidate_year,
                genres=series_genres,
            )
            episode = Episode(
                season_number=season_num,
                episode_number=episode_num,
                title=episode_title,
                codec_video=codec_video,
                codec_audio=codec_audio,
                resolution=resolution_str,
                languages=languages,
                file_size_bytes=file_size_bytes,
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
            series_repo = container.series_repository()
            saved_series = series_repo.save(series)

            # Sauvegarder l'episode en base
            episode.series_id = saved_series.id
            episode_repo = container.episode_repository()
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
            ) = await _enrich_movie_metadata(str(candidate_id), tmdb_client, container)

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
                duration_seconds=movie_details.duration_seconds if movie_details else None,
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
            movie_repo = container.movie_repository()
            saved_movie = movie_repo.save(movie)

            # Afficher le feedback de sauvegarde avec les notes
            year_str = f" ({movie.year})" if movie.year else ""
            tmdb_str = f"TMDB: {movie.vote_average:.1f}/10" if movie.vote_average else "TMDB: -"
            imdb_str = f"IMDb: {movie.imdb_rating:.1f}/10" if movie.imdb_rating else "IMDb: -"
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

    return transfers
