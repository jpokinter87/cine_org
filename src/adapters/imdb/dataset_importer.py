"""
Gestionnaire d'import des datasets IMDb.

Telecharge et importe les datasets IMDb publics dans la base locale.
Les datasets sont caches localement pour eviter les telechargements repetitifs.

Datasets supportes:
- title.ratings.tsv.gz: Notes et nombre de votes

Documentation: https://www.imdb.com/interfaces/
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import httpx
from sqlmodel import Session, select

from src.adapters.imdb.tsv_parser import TSVParser
from src.infrastructure.persistence.models import IMDbAkaModel, IMDbRatingModel
from src.utils.helpers import normalize_accents


# Langues retenues par défaut pour title.akas (filtre raisonnable : couvre
# les principaux marchés européens + asiatiques sans exploser la DB).
# Le dataset complet fait ~35M lignes ; ce filtre le réduit à ~5-8M.
DEFAULT_AKA_LANGUAGES: frozenset[str] = frozenset({
    "fr", "en", "ja", "ko", "es", "de", "it", "pt", "zh",
    "ru", "ar", "nl", "pl", "sv", "da", "no", "fi", "cs",
    "hu", "tr", "he", "hi", "vi", "th", "id", "ms", "el",
})

# Régions retenues quand language est manquant (\\N). Un titre peut avoir
# region=FR sans language explicite — on le garde quand même.
DEFAULT_AKA_REGIONS: frozenset[str] = frozenset({
    "FR", "US", "GB", "CA", "JP", "KR", "ES", "DE", "IT",
    "PT", "BR", "NL", "BE", "CH", "AU", "NZ", "RU", "CN",
    "TW", "HK", "MX", "AR", "IN", "TR", "PL", "SE", "DK",
    "NO", "FI", "GR", "IL", "AE", "TH", "VN", "ID", "MY",
})


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

    def import_akas(
        self,
        file_path: Path,
        *,
        languages: Optional[frozenset[str]] = None,
        regions: Optional[frozenset[str]] = None,
        batch_size: int = 10000,
        on_progress: Optional["callable"] = None,
    ) -> IMDbDatasetStats:
        """
        Importe les titres alternatifs IMDb depuis title.akas.tsv.gz.

        Filtre par langues et régions pour réduire la table à un sous-ensemble
        utile (sans ce filtre, ~35M lignes). Les akas dont language ET region
        sont absents/non listés sont skippés.

        La table existante est purgée avant l'import (full refresh) — c'est
        un dataset versionné par snapshot IMDb, pas incrémental.

        Mémoire : utilise `session.execute(insert(table), batch_dicts)`
        (SQLAlchemy core) au lieu de `session.add(Model(...))` pour
        bypasser l'Identity Map. Commit à chaque batch pour libérer le
        WAL SQLite. Pic mémoire constant indépendamment du nombre de
        lignes (sinon : OOM sur 5-8M lignes accumulées en Identity Map).

        Args:
            file_path: Chemin vers le fichier title.akas.tsv(.gz)
            languages: Langues retenues (ISO 639-1). Défaut: DEFAULT_AKA_LANGUAGES.
            regions: Régions retenues (codes pays). Défaut: DEFAULT_AKA_REGIONS.
            batch_size: Taille des batches d'insertion (défaut 10000).

        Returns:
            Statistiques d'import
        """
        from sqlalchemy import delete, insert

        lang_filter = languages if languages is not None else DEFAULT_AKA_LANGUAGES
        region_filter = regions if regions is not None else DEFAULT_AKA_REGIONS

        # Full refresh : vide la table avant import (dataset = snapshot
        # complet, pas de notion d'incremental). Commit immédiat pour
        # libérer le WAL.
        table = IMDbAkaModel.__table__
        self._session.execute(delete(table))
        self._session.commit()

        stats = IMDbDatasetStats()
        batch: list[dict] = []

        for record in self._parser.parse_akas(file_path):
            stats.total += 1

            lang = record.get("language")
            region = record.get("region")
            # Garder si language listé OU (language absent ET region listée).
            keep = (
                (lang is not None and lang in lang_filter)
                or (lang is None and region is not None and region in region_filter)
            )
            if not keep:
                stats.skipped += 1
                continue

            title = record["title"]
            if not title:
                stats.skipped += 1
                continue

            batch.append({
                "tconst": record["tconst"],
                "title": title,
                "title_normalized": normalize_accents(title).lower().strip(),
                "region": region,
                "language": lang,
            })

            if len(batch) >= batch_size:
                self._session.execute(insert(table), batch)
                self._session.commit()
                stats.imported += len(batch)
                batch = []
                if on_progress is not None:
                    on_progress(stats)

        if batch:
            self._session.execute(insert(table), batch)
            self._session.commit()
            stats.imported += len(batch)
            if on_progress is not None:
                on_progress(stats)

        return stats

    def search_akas(
        self, query: str, *, limit: int = 20
    ) -> list[str]:
        """Recherche les tconst dont au moins un aka match la query.

        Match exact sur `title_normalized` (lowercase + sans accents).
        Retourne les tconst uniques, triés par fréquence d'apparition
        décroissante (plus une variante existe, plus c'est probable).

        Args:
            query: Titre à chercher (n'importe quelle casse / accents).
            limit: Nombre max de tconst retournés.

        Returns:
            Liste de tconst (ex: ["tt0082416", "tt0099999"]).
        """
        normalized = normalize_accents(query).lower().strip()
        if not normalized:
            return []

        from sqlalchemy import func

        statement = (
            select(IMDbAkaModel.tconst, func.count().label("n"))
            .where(IMDbAkaModel.title_normalized == normalized)
            .group_by(IMDbAkaModel.tconst)
            .order_by(func.count().desc())
            .limit(limit)
        )
        return [row[0] for row in self._session.exec(statement).all()]

    def get_akas_stats(self) -> dict:
        """Retourne les statistiques de la table d'akas."""
        from sqlalchemy import func

        count_stmt = select(func.count()).select_from(IMDbAkaModel)
        count = self._session.exec(count_stmt).one()
        tconst_stmt = select(func.count(func.distinct(IMDbAkaModel.tconst)))
        unique_tconsts = self._session.exec(tconst_stmt).one()
        return {"count": count, "unique_tconsts": unique_tconsts}

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
