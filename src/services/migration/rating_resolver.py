"""
Resolveur de notes pour la migration NAS.

Pour un MigrationCandidate donné, retrouve l'œuvre correspondante en base
(MovieModel ou SeriesModel) via parsing du nom de fichier, puis combine les
notes IMDb / TMDB / personnelle pour produire une RatingDecision.

La note retenue est `max(imdb_rating, vote_average, personal_rating × weight)`
avec `weight=2` par défaut (échelle personnelle 1-5 → 0-10). Les notes
manquantes ne participent pas à la combinaison.

Si aucune note n'est trouvée en base mais que l'imdb_id est connu, on
interroge le cache IMDb local (IMDbDatasetImporter).
"""

from __future__ import annotations

from typing import Optional

from sqlmodel import Session, select

from src.adapters.imdb.dataset_importer import IMDbDatasetImporter
from src.core.ports.parser import IFilenameParser
from src.core.value_objects.parsed_info import MediaType, ParsedFilename
from src.infrastructure.persistence.models import MovieModel, SeriesModel
from src.services.migration.dataclasses import MigrationCandidate, RatingDecision


class MigrationRatingResolver:
    """
    Résoud la note d'un candidat de migration.

    Args:
        session: Session SQLModel ouverte sur la base CineOrg.
        parser: Parser de noms de fichiers (guessit) pour extraire titre/année/type.
        imdb_importer: Cache IMDb local pour les notes imdb manquantes en DB.
        personal_weight: Multiplicateur de la note personnelle (défaut 2 →
            une note 5/5 vaut 10/10 dans la combinaison).
    """

    def __init__(
        self,
        session: Session,
        parser: IFilenameParser,
        imdb_importer: IMDbDatasetImporter,
        personal_weight: int = 2,
    ) -> None:
        self._session = session
        self._parser = parser
        self._imdb_importer = imdb_importer
        self._personal_weight = personal_weight

    def resolve(self, candidate: MigrationCandidate) -> RatingDecision:
        """Retourne la décision de note pour ce candidat."""
        parsed = self._parser.parse(candidate.symlink_path.name)
        media_type = self._guess_media_type(candidate, parsed)
        if media_type == MediaType.SERIES:
            return self._resolve_series(parsed)
        return self._resolve_movie(parsed)

    def _resolve_movie(self, parsed: ParsedFilename) -> RatingDecision:
        movie = self._find_movie(parsed)
        if movie is None:
            return RatingDecision()
        imdb = self._effective_imdb(movie.imdb_rating, movie.imdb_id)
        tmdb = movie.vote_average
        personal = movie.personal_rating
        value, source = self._combine(imdb, tmdb, personal)
        return RatingDecision(
            value=value,
            source=source,
            imdb=imdb,
            tmdb=tmdb,
            personal=personal,
            movie_id_in_db=movie.id,
            title_match=movie.title,
        )

    def _resolve_series(self, parsed: ParsedFilename) -> RatingDecision:
        series = self._find_series(parsed)
        if series is None:
            return RatingDecision()
        imdb = self._effective_imdb(series.imdb_rating, series.imdb_id)
        tmdb = series.vote_average
        personal = series.personal_rating
        value, source = self._combine(imdb, tmdb, personal)
        return RatingDecision(
            value=value,
            source=source,
            imdb=imdb,
            tmdb=tmdb,
            personal=personal,
            series_id_in_db=series.id,
            title_match=series.title,
        )

    def _find_movie(self, parsed: ParsedFilename) -> Optional[MovieModel]:
        if not parsed.title:
            return None
        # Match exact d'abord (titre + année si dispo)
        stmt = select(MovieModel).where(MovieModel.title == parsed.title)
        if parsed.year:
            stmt = stmt.where(MovieModel.year == parsed.year)
        result = self._session.exec(stmt).first()
        if result is not None:
            return result
        # Fallback : recherche par sous-chaîne
        stmt = select(MovieModel).where(MovieModel.title.contains(parsed.title))
        if parsed.year:
            stmt = stmt.where(MovieModel.year == parsed.year)
        return self._session.exec(stmt).first()

    def _find_series(self, parsed: ParsedFilename) -> Optional[SeriesModel]:
        if not parsed.title:
            return None
        stmt = select(SeriesModel).where(SeriesModel.title == parsed.title)
        if parsed.year:
            stmt = stmt.where(SeriesModel.year == parsed.year)
        result = self._session.exec(stmt).first()
        if result is not None:
            return result
        stmt = select(SeriesModel).where(SeriesModel.title.contains(parsed.title))
        if parsed.year:
            stmt = stmt.where(SeriesModel.year == parsed.year)
        return self._session.exec(stmt).first()

    def _effective_imdb(
        self, db_value: Optional[float], imdb_id: Optional[str]
    ) -> Optional[float]:
        """Retourne db_value si dispo, sinon va lire le cache IMDb local."""
        if db_value is not None:
            return db_value
        if not imdb_id:
            return None
        rating = self._imdb_importer.get_rating(imdb_id)
        if rating:
            return rating[0]
        return None

    def _combine(
        self,
        imdb: Optional[float],
        tmdb: Optional[float],
        personal: Optional[int],
    ) -> tuple[Optional[float], Optional[str]]:
        candidates: list[tuple[float, str]] = []
        if imdb is not None:
            candidates.append((float(imdb), "imdb"))
        if tmdb is not None:
            candidates.append((float(tmdb), "tmdb"))
        if personal is not None:
            candidates.append((float(personal * self._personal_weight), "personal"))
        if not candidates:
            return None, None
        return max(candidates, key=lambda x: x[0])

    @staticmethod
    def _guess_media_type(
        candidate: MigrationCandidate, parsed: ParsedFilename
    ) -> MediaType:
        if parsed.media_type != MediaType.UNKNOWN:
            return parsed.media_type
        media_root = (candidate.media_root or "").lower()
        if media_root.startswith("séri") or media_root.startswith("seri"):
            return MediaType.SERIES
        if media_root.startswith("anim"):
            return MediaType.SERIES
        return MediaType.MOVIE
