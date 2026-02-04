"""
Gestionnaire d'import des datasets IMDb.

Telecharge et importe les datasets IMDb publics dans la base locale.
Les datasets sont caches localement pour eviter les telechargements repetitifs.

Datasets supportes:
- title.ratings.tsv.gz: Notes et nombre de votes

Documentation: https://www.imdb.com/interfaces/
"""

import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import httpx
from sqlmodel import Session, select

from src.adapters.imdb.tsv_parser import TSVParser
from src.infrastructure.persistence.models import IMDbRatingModel


# URL de base des datasets IMDb
IMDB_DATASETS_BASE_URL = "https://datasets.imdbws.com"


@dataclass
class IMDbDatasetStats:
    """Statistiques d'import des datasets IMDb."""

    total: int = 0
    imported: int = 0
    skipped: int = 0
    errors: int = 0


class IMDbDatasetImporter:
    """
    Gestionnaire d'import des datasets IMDb.

    Telecharge, cache et importe les datasets IMDb dans la base locale.
    """

    def __init__(
        self,
        cache_dir: Path,
        session: Session,
    ) -> None:
        """
        Initialise le gestionnaire d'import.

        Args:
            cache_dir: Repertoire pour le cache des fichiers telecharges
            session: Session SQLModel pour les operations DB
        """
        self._cache_dir = Path(cache_dir)
        self._session = session
        self._parser = TSVParser()

        # Creer le repertoire de cache si necessaire
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def needs_update(self, file_path: Path, max_age_days: int = 7) -> bool:
        """
        Verifie si un fichier de dataset doit etre mis a jour.

        Args:
            file_path: Chemin vers le fichier
            max_age_days: Age maximum en jours avant mise a jour

        Returns:
            True si le fichier n'existe pas ou est trop vieux
        """
        if not file_path.exists():
            return True

        # Verifier l'age du fichier
        mtime = file_path.stat().st_mtime
        file_date = date.fromtimestamp(mtime)
        age = (date.today() - file_date).days

        return age >= max_age_days

    async def download_dataset(self, name: str) -> Path:
        """
        Telecharge un dataset IMDb.

        Args:
            name: Nom du dataset (ex: "title.ratings")

        Returns:
            Chemin vers le fichier telecharge

        Raises:
            httpx.HTTPStatusError: Si le telechargement echoue
        """
        url = f"{IMDB_DATASETS_BASE_URL}/{name}.tsv.gz"
        file_path = self._cache_dir / f"{name}.tsv.gz"

        async with httpx.AsyncClient() as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()

                # Telecharger en streaming pour gerer les gros fichiers
                with open(file_path, "wb") as f:
                    async for chunk in response.aiter_bytes():
                        f.write(chunk)

        return file_path

    def import_ratings(self, file_path: Path) -> IMDbDatasetStats:
        """
        Importe les notes IMDb depuis un fichier title.ratings.tsv.gz.

        Les enregistrements existants sont mis a jour avec UPSERT.

        Args:
            file_path: Chemin vers le fichier TSV

        Returns:
            Statistiques d'import
        """
        from sqlalchemy import text

        stats = IMDbDatasetStats()

        # Utiliser une transaction avec insertion en batch
        batch_size = 1000
        batch = []

        for record in self._parser.parse_ratings(file_path):
            stats.total += 1

            batch.append({
                "tconst": record["tconst"],
                "average_rating": record["average_rating"],
                "num_votes": record["num_votes"],
                "last_updated": date.today(),
            })

            if len(batch) >= batch_size:
                self._insert_batch(batch)
                stats.imported += len(batch)
                batch = []

        # Inserer le dernier batch
        if batch:
            self._insert_batch(batch)
            stats.imported += len(batch)

        self._session.commit()

        return stats

    def _insert_batch(self, batch: list[dict]) -> None:
        """
        Insere un batch d'enregistrements avec UPSERT.

        Args:
            batch: Liste de dictionnaires avec les donnees
        """
        from sqlalchemy import text

        # SQLite UPSERT via INSERT OR REPLACE
        for record in batch:
            model = IMDbRatingModel(
                tconst=record["tconst"],
                average_rating=record["average_rating"],
                num_votes=record["num_votes"],
                last_updated=record["last_updated"],
            )
            # Merge pour faire un upsert
            self._session.merge(model)

    def get_rating(self, imdb_id: str) -> Optional[tuple[float, int]]:
        """
        Recupere les notes IMDb pour un ID donne.

        Args:
            imdb_id: ID IMDb (ex: "tt0499549")

        Returns:
            Tuple (average_rating, num_votes), ou None si non trouve
        """
        statement = select(
            IMDbRatingModel.average_rating,
            IMDbRatingModel.num_votes,
        ).where(IMDbRatingModel.tconst == imdb_id)

        result = self._session.exec(statement).first()

        return result if result else None

    def get_stats(self) -> dict:
        """
        Retourne les statistiques du cache IMDb local.

        Returns:
            Dictionnaire avec le nombre d'enregistrements et la date de mise a jour
        """
        from sqlalchemy import func

        # Compter les enregistrements
        count_stmt = select(func.count()).select_from(IMDbRatingModel)
        count = self._session.exec(count_stmt).one()

        # Date de derniere mise a jour
        date_stmt = select(func.max(IMDbRatingModel.last_updated))
        last_updated = self._session.exec(date_stmt).first()

        return {
            "count": count,
            "last_updated": last_updated,
        }
