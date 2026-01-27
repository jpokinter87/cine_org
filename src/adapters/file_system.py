"""
Adaptateur pour les operations sur le systeme de fichiers.

Implementation concrete de IFileSystem pour les operations fichiers reelles.
Fournit egalement des methodes utilitaires pour le scan de fichiers video.
"""

import hashlib
import os
import shutil
import uuid
from pathlib import Path
from typing import Iterator, Optional

from src.core.ports.file_system import IFileSystem, ISymlinkManager
from src.core.value_objects import MediaInfo

# Extensions video supportees
VIDEO_EXTENSIONS: frozenset[str] = frozenset({
    ".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v"
})

# Patterns a ignorer dans les noms de fichiers (insensible a la casse)
IGNORED_PATTERNS: frozenset[str] = frozenset({
    "sample", "trailer", "preview", "extras", "bonus"
})

# Taille du chunk pour le calcul de hash (10 MB)
HASH_CHUNK_SIZE: int = 10 * 1024 * 1024


class FileSystemAdapter(IFileSystem, ISymlinkManager):
    """
    Implementation de IFileSystem et ISymlinkManager pour le systeme de fichiers reel.

    Fournit les operations basiques sur les fichiers (exists, move, copy, delete)
    ainsi que des methodes utilitaires pour le scan de fichiers video.
    """

    def exists(self, path: Path) -> bool:
        """Verifie si un chemin existe."""
        return path.exists()

    def read_metadata(self, path: Path) -> Optional[MediaInfo]:
        """
        Lit les metadonnees techniques d'un fichier video.

        NOTE: Cette methode retourne None pour l'instant.
        L'extraction mediainfo sera implementee via IMediaInfoExtractor
        qui est injecte separement dans les services qui en ont besoin.
        """
        return None

    def move(self, source: Path, destination: Path) -> bool:
        """
        Deplace un fichier de la source vers la destination.

        Cree les repertoires parents si necessaire.
        """
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            return True
        except (OSError, shutil.Error):
            return False

    def copy(self, source: Path, destination: Path) -> bool:
        """
        Copie un fichier de la source vers la destination.

        Cree les repertoires parents si necessaire.
        """
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(source), str(destination))
            return True
        except (OSError, shutil.Error):
            return False

    def delete(self, path: Path) -> bool:
        """Supprime un fichier."""
        try:
            path.unlink()
            return True
        except OSError:
            return False

    def calculate_hash(self, path: Path) -> Optional[str]:
        """
        Calcule le hash SHA-256 des premiers 10MB du fichier.

        Utilise seulement les premiers 10MB pour la performance
        sur les gros fichiers video.
        """
        try:
            hasher = hashlib.sha256()
            with open(path, "rb") as f:
                chunk = f.read(HASH_CHUNK_SIZE)
                hasher.update(chunk)
            return hasher.hexdigest()
        except OSError:
            return None

    def get_size(self, path: Path) -> int:
        """
        Recupere la taille du fichier en octets.

        Retourne 0 si le fichier n'existe pas.
        """
        try:
            return path.stat().st_size
        except OSError:
            return 0

    def atomic_move(self, source: Path, destination: Path) -> bool:
        """
        Deplace un fichier de maniere atomique.

        Utilise os.replace pour un deplacement atomique sur le meme filesystem.
        Pour un deplacement cross-filesystem, utilise une copie intermediaire
        avec un fichier temporaire pour garantir l'atomicite.

        Args:
            source: Chemin du fichier source
            destination: Chemin de destination

        Returns:
            True si le deplacement a reussi, False sinon.
        """
        try:
            # Creer les repertoires parents si necessaire
            destination.parent.mkdir(parents=True, exist_ok=True)

            # Tentative de rename atomique (fonctionne sur le meme filesystem)
            try:
                os.replace(source, destination)
            except OSError:
                # Cross-filesystem: copie intermediaire avec fichier temporaire
                # Nom temporaire unique pour eviter les collisions
                temp_name = f".tmp_{uuid.uuid4().hex}_{destination.name}"
                temp = destination.with_name(temp_name)
                try:
                    # Copie avec preservation des metadonnees
                    shutil.copy2(source, temp)
                    # Rename atomique du temp vers destination
                    os.replace(temp, destination)
                    # Suppression de la source
                    source.unlink()
                except Exception:
                    # Nettoyer le fichier temporaire en cas d'erreur
                    if temp.exists():
                        temp.unlink()
                    raise

            return True
        except Exception:
            return False

    # Implementation de ISymlinkManager

    def create_symlink(self, target: Path, link: Path) -> bool:
        """
        Cree un lien symbolique.

        Args:
            target: Chemin vers lequel le lien pointe (le fichier reel)
            link: Chemin ou le lien symbolique sera cree
        """
        try:
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(target)
            return True
        except OSError:
            return False

    def remove_symlink(self, link: Path) -> bool:
        """Supprime un lien symbolique."""
        try:
            if link.is_symlink():
                link.unlink()
                return True
            return False
        except OSError:
            return False

    def is_symlink(self, path: Path) -> bool:
        """Verifie si un chemin est un lien symbolique."""
        return path.is_symlink()

    def resolve_target(self, link: Path) -> Optional[Path]:
        """
        Resout la cible d'un lien symbolique.

        Retourne None si ce n'est pas un lien ou s'il est casse.
        """
        try:
            if link.is_symlink():
                resolved = link.resolve()
                if resolved.exists():
                    return resolved
            return None
        except OSError:
            return None

    def find_broken_links(self, directory: Path) -> list[Path]:
        """
        Trouve tous les liens symboliques casses dans un repertoire (recursif).
        """
        broken: list[Path] = []
        try:
            for path in directory.rglob("*"):
                if path.is_symlink() and not path.resolve().exists():
                    broken.append(path)
        except OSError:
            pass
        return broken

    # Methodes utilitaires pour le scan

    def list_video_files(
        self,
        directory: Path,
        min_file_size_bytes: int = 0,
    ) -> Iterator[Path]:
        """
        Liste les fichiers video dans un repertoire (recursif).

        Filtre:
        - Par extension (VIDEO_EXTENSIONS)
        - Exclut les symlinks
        - Exclut les fichiers contenant IGNORED_PATTERNS
        - Exclut les fichiers < min_file_size_bytes

        Args:
            directory: Repertoire a scanner
            min_file_size_bytes: Taille minimale en octets (defaut: 0)

        Yields:
            Chemins vers les fichiers video valides
        """
        if not directory.exists():
            return

        for path in directory.rglob("*"):
            # Ignorer les repertoires
            if path.is_dir():
                continue

            # Ignorer les symlinks
            if path.is_symlink():
                continue

            # Verifier l'extension
            if path.suffix.lower() not in VIDEO_EXTENSIONS:
                continue

            # Verifier les patterns ignores (insensible a la casse)
            filename_lower = path.name.lower()
            if any(pattern in filename_lower for pattern in IGNORED_PATTERNS):
                continue

            # Verifier la taille minimale
            try:
                if path.stat().st_size < min_file_size_bytes:
                    continue
            except OSError:
                continue

            yield path
