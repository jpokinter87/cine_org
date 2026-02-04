"""
Parser pour les fichiers TSV des datasets IMDb.

Les datasets IMDb sont distribues sous forme de fichiers TSV compresses (.tsv.gz).
Ce parser gere la lecture de ces fichiers en mode streaming pour minimiser
l'utilisation memoire.

Datasets supportes:
- title.ratings.tsv.gz: Notes et nombre de votes
- title.basics.tsv.gz: Informations de base (titre, annee, duree, genres)

Documentation: https://www.imdb.com/interfaces/
"""

import gzip
from pathlib import Path
from typing import Generator


class TSVParser:
    """
    Parser pour les fichiers TSV des datasets IMDb.

    Lit les fichiers en mode streaming (generateur) pour minimiser
    l'utilisation memoire, particulierement important pour les gros
    fichiers (title.basics fait ~600MB decompresse).
    """

    def parse_ratings(self, file_path: Path) -> Generator[dict, None, None]:
        """
        Parse le fichier title.ratings.tsv(.gz).

        Format du fichier:
        tconst    averageRating    numVotes
        tt0000001    5.7    1941

        Args:
            file_path: Chemin vers le fichier TSV (compresse ou non)

        Yields:
            Dictionnaire avec:
            - tconst: ID IMDb (ex: "tt0499549")
            - average_rating: Note moyenne (float)
            - num_votes: Nombre de votes (int)

        Raises:
            FileNotFoundError: Si le fichier n'existe pas
        """
        if not file_path.exists():
            raise FileNotFoundError(f"Fichier non trouve: {file_path}")

        open_fn = gzip.open if file_path.suffix == ".gz" else open
        mode = "rt"

        with open_fn(file_path, mode, encoding="utf-8") as f:
            # Ignorer l'en-tete
            next(f)

            for line in f:
                parts = line.strip().split("\t")
                if len(parts) >= 3:
                    yield {
                        "tconst": parts[0],
                        "average_rating": float(parts[1]),
                        "num_votes": int(parts[2]),
                    }

    def parse_basics(self, file_path: Path) -> Generator[dict, None, None]:
        """
        Parse le fichier title.basics.tsv(.gz).

        Format du fichier:
        tconst    titleType    primaryTitle    originalTitle    isAdult    startYear    endYear    runtimeMinutes    genres
        tt0499549    movie    Avatar    Avatar    0    2009    \\N    162    Action,Adventure,Fantasy

        Args:
            file_path: Chemin vers le fichier TSV (compresse ou non)

        Yields:
            Dictionnaire avec:
            - tconst: ID IMDb (ex: "tt0499549")
            - title_type: Type de titre (movie, tvSeries, etc.)
            - primary_title: Titre principal
            - original_title: Titre original
            - is_adult: Boolean
            - start_year: Annee de debut (int ou None)
            - end_year: Annee de fin (int ou None)
            - runtime_minutes: Duree en minutes (int ou None)
            - genres: Liste de genres

        Raises:
            FileNotFoundError: Si le fichier n'existe pas
        """
        if not file_path.exists():
            raise FileNotFoundError(f"Fichier non trouve: {file_path}")

        open_fn = gzip.open if file_path.suffix == ".gz" else open
        mode = "rt"

        with open_fn(file_path, mode, encoding="utf-8") as f:
            # Ignorer l'en-tete
            next(f)

            for line in f:
                parts = line.strip().split("\t")
                if len(parts) >= 9:
                    yield {
                        "tconst": parts[0],
                        "title_type": parts[1],
                        "primary_title": parts[2],
                        "original_title": parts[3],
                        "is_adult": parts[4] == "1",
                        "start_year": self._parse_int(parts[5]),
                        "end_year": self._parse_int(parts[6]),
                        "runtime_minutes": self._parse_int(parts[7]),
                        "genres": parts[8].split(",") if parts[8] != "\\N" else [],
                    }

    @staticmethod
    def _parse_int(value: str) -> int | None:
        """Parse une valeur entiere, retourne None pour \\N."""
        if value == "\\N":
            return None
        try:
            return int(value)
        except ValueError:
            return None
