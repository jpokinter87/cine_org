"""
Index des fichiers video pour la recherche de cibles de reparation.

Construit et gere un index en memoire (avec cache persistant) de tous
les fichiers video dans le repertoire de stockage.
"""

import json
import time
from pathlib import Path
from typing import Optional

from loguru import logger

from .filename_analyzer import extract_clean_title, normalize_filename


class FileIndexer:
    """
    Construit et gere un index de fichiers video pour la recherche rapide.

    L'index est stocke en memoire et peut etre persiste dans un cache JSON.
    """

    def __init__(self, storage_dir: Optional[Path] = None) -> None:
        self._storage_dir = storage_dir
        self._file_index: list[tuple[Path, str, str]] = []
        self._index_built = False

    @property
    def file_index(self) -> list[tuple[Path, str, str]]:
        """Retourne l'index des fichiers."""
        return self._file_index

    @property
    def index_built(self) -> bool:
        """Indique si l'index a ete construit."""
        return self._index_built

    def _get_index_cache_path(self) -> Path:
        """Retourne le chemin du fichier cache de l'index, unique par storage_dir."""
        import hashlib

        cache_dir = Path.home() / ".cineorg"
        cache_dir.mkdir(parents=True, exist_ok=True)
        # Hash du storage_dir pour eviter les collisions (tests vs production)
        dir_hash = hashlib.md5(str(self._storage_dir).encode()).hexdigest()[:8]
        return cache_dir / f"file_index_{dir_hash}.json"

    def _load_cached_index(self, max_age_hours: int = 24, scan_all: bool = False) -> bool:
        """
        Charge l'index depuis le cache s'il existe et n'est pas trop vieux.

        Args:
            max_age_hours: Age maximum du cache en heures
            scan_all: Le scope demande (doit correspondre au cache)

        Returns:
            True si l'index a ete charge depuis le cache
        """
        cache_path = self._get_index_cache_path()
        if not cache_path.exists():
            return False

        try:
            # Verifier l'age du cache
            cache_age = time.time() - cache_path.stat().st_mtime
            if cache_age > max_age_hours * 3600:
                logger.debug(f"Cache d'index trop vieux ({cache_age/3600:.1f}h)")
                return False

            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Verifier que le storage_dir correspond
            if data.get("storage_dir") != str(self._storage_dir):
                logger.debug("Cache d'index pour un autre storage_dir")
                return False

            # Verifier la version du cache (version 3 requis pour scan_all)
            cache_version = data.get("version", 1)
            if cache_version < 3:
                logger.debug("Cache d'index version obsolete, reconstruction necessaire")
                return False

            # Verifier que le scope correspond
            cached_scan_all = data.get("scan_all", False)
            if scan_all and not cached_scan_all:
                # On demande scan_all mais le cache est partiel → reconstruire
                logger.debug("Cache partiel, scan_all demande → reconstruction")
                return False
            # Note: un cache scan_all=True est reutilisable pour scan_all=False
            # car il contient un surensemble des fichiers

            # Charger l'index
            self._file_index = [
                (Path(item["path"]), item["normalized"], item.get("clean_title", ""))
                for item in data.get("files", [])
            ]
            self._index_built = True
            scope = "complet" if cached_scan_all else "Films/Séries"
            logger.debug(f"Index charge depuis le cache ({scope}): {len(self._file_index)} fichiers")
            return True

        except (json.JSONDecodeError, KeyError, OSError) as e:
            logger.debug(f"Erreur chargement cache d'index: {e}")
            return False

    def _save_index_to_cache(self, scan_all: bool = False) -> None:
        """Sauvegarde l'index dans le cache."""
        cache_path = self._get_index_cache_path()
        try:
            data = {
                "version": 3,
                "storage_dir": str(self._storage_dir),
                "scan_all": scan_all,
                "files": [
                    {"path": str(path), "normalized": norm, "clean_title": clean}
                    for path, norm, clean in self._file_index
                ],
            }
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            logger.debug(f"Index sauvegarde dans le cache: {cache_path}")
        except OSError as e:
            logger.warning(f"Impossible de sauvegarder le cache d'index: {e}")

    def build_file_index(
        self,
        progress_callback: Optional[callable] = None,
        force_rebuild: bool = False,
        max_cache_age_hours: int = 24,
        scan_all: bool = False,
    ) -> int:
        """
        Construit un index de tous les fichiers video dans storage.

        Utilise un cache persistant pour eviter de rescanner a chaque commande.
        Par defaut, limite l'indexation aux repertoires Films et Series.
        Avec scan_all=True, scanne tous les sous-repertoires de storage.

        Args:
            progress_callback: Fonction appelee avec (fichiers_indexes, message)
            force_rebuild: Force la reconstruction meme si le cache est valide
            max_cache_age_hours: Age maximum du cache en heures (defaut: 24h)
            scan_all: Scanner tous les sous-repertoires (pas seulement Films/Series)

        Returns:
            Nombre de fichiers indexes
        """
        from src.adapters.file_system import VIDEO_EXTENSIONS

        if not self._storage_dir or not self._storage_dir.exists():
            return 0

        # Essayer de charger depuis le cache
        if not force_rebuild and self._load_cached_index(max_cache_age_hours, scan_all=scan_all):
            if progress_callback:
                progress_callback(len(self._file_index), f"Index charge (cache): {len(self._file_index)} fichiers")
            return len(self._file_index)

        self._file_index = []
        count = 0

        if scan_all:
            # Scanner tous les sous-repertoires de storage
            media_dirs = [self._storage_dir]
            if progress_callback:
                progress_callback(count, f"Scan complet: {self._storage_dir}")
        else:
            # Limiter aux repertoires de videos (Films et Series)
            media_dirs = []
            for subdir in ["Films", "Séries", "Series"]:
                media_path = self._storage_dir / subdir
                if media_path.exists():
                    media_dirs.append(media_path)
                    if progress_callback:
                        progress_callback(count, f"Scan: {media_path}")

            # Fallback: si aucun sous-repertoire Films/Series, scanner storage_dir
            if not media_dirs:
                media_dirs = [self._storage_dir]

        for media_dir in media_dirs:
            for candidate in media_dir.rglob("*"):
                try:
                    # Verifier symlink EN PREMIER
                    if candidate.is_symlink():
                        continue
                    if candidate.is_dir():
                        continue

                    # Verifier que c'est un fichier video
                    if candidate.suffix.lower() not in VIDEO_EXTENSIONS:
                        continue

                    # Normaliser le nom pour comparaison rapide
                    normalized = normalize_filename(candidate.name)
                    # Extraire aussi le titre nettoye (sans termes techniques)
                    clean_title = extract_clean_title(candidate.name)
                    self._file_index.append((candidate, normalized, clean_title))
                    count += 1

                    if progress_callback and count % 500 == 0:
                        progress_callback(count, f"Indexation: {count} fichiers...")

                except (PermissionError, OSError):
                    continue

        self._index_built = True

        # Sauvegarder dans le cache
        self._save_index_to_cache(scan_all=scan_all)

        if progress_callback:
            progress_callback(count, f"Index construit: {count} fichiers")

        return count
