"""
Interfaces ports pour le système de fichiers.

Interfaces abstraites (ports) définissant les contrats pour les opérations fichiers.
Les implémentations (adaptateurs) fourniront l'accès concret au système de fichiers
et la gestion des liens symboliques.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from src.core.value_objects import MediaInfo


class IFileSystem(ABC):
    """
    Interface pour les opérations de base sur les fichiers.

    Définit les opérations pour interagir avec le système de fichiers :
    vérification d'existence, lecture des métadonnées, déplacement/copie de fichiers.
    """

    @abstractmethod
    def exists(self, path: Path) -> bool:
        """Vérifie si un chemin existe."""
        ...

    @abstractmethod
    def read_metadata(self, path: Path) -> Optional[MediaInfo]:
        """
        Lit les métadonnées techniques d'un fichier vidéo.

        Utilise mediainfo pour extraire résolution, codecs, langues, durée.

        Args :
            path : Chemin vers le fichier vidéo

        Retourne :
            MediaInfo avec les métadonnées extraites, ou None si l'extraction échoue
        """
        ...

    @abstractmethod
    def move(self, source: Path, destination: Path) -> bool:
        """
        Déplace un fichier de la source vers la destination.

        Crée les répertoires parents si nécessaire.

        Args :
            source : Chemin actuel du fichier
            destination : Chemin cible du fichier

        Retourne :
            True si réussi, False sinon
        """
        ...

    @abstractmethod
    def copy(self, source: Path, destination: Path) -> bool:
        """
        Copie un fichier de la source vers la destination.

        Crée les répertoires parents si nécessaire.

        Args :
            source : Chemin du fichier source
            destination : Chemin du fichier cible

        Retourne :
            True si réussi, False sinon
        """
        ...

    @abstractmethod
    def delete(self, path: Path) -> bool:
        """
        Supprime un fichier.

        Args :
            path : Chemin à supprimer

        Retourne :
            True si supprimé, False sinon
        """
        ...

    @abstractmethod
    def calculate_hash(self, path: Path) -> Optional[str]:
        """
        Calcule le hash du contenu (SHA-256) pour la déduplication.

        Args :
            path : Chemin vers le fichier

        Retourne :
            Hash SHA-256 encodé en hexadécimal, ou None si le calcul échoue
        """
        ...

    @abstractmethod
    def get_size(self, path: Path) -> int:
        """
        Récupère la taille du fichier en octets.

        Args :
            path : Chemin vers le fichier

        Retourne :
            Taille du fichier en octets, ou 0 si le fichier n'existe pas
        """
        ...


class ISymlinkManager(ABC):
    """
    Interface de gestion des liens symboliques.

    Définit les opérations pour créer et gérer les liens symboliques.
    Utilisée pour le répertoire video/ qui reflète la structure de storage/.
    """

    @abstractmethod
    def create_symlink(self, target: Path, link: Path) -> bool:
        """
        Crée un lien symbolique.

        Args :
            target : Chemin vers lequel le lien pointe (le fichier réel)
            link : Chemin où le lien symbolique sera créé

        Retourne :
            True si créé avec succès, False sinon
        """
        ...

    @abstractmethod
    def remove_symlink(self, link: Path) -> bool:
        """
        Supprime un lien symbolique.

        Args :
            link : Chemin du lien symbolique à supprimer

        Retourne :
            True si supprimé, False sinon
        """
        ...

    @abstractmethod
    def is_symlink(self, path: Path) -> bool:
        """Vérifie si un chemin est un lien symbolique."""
        ...

    @abstractmethod
    def resolve_target(self, link: Path) -> Optional[Path]:
        """
        Résout la cible d'un lien symbolique.

        Args :
            link : Chemin vers le lien symbolique

        Retourne :
            Chemin cible résolu, ou None si ce n'est pas un lien ou s'il est cassé
        """
        ...

    @abstractmethod
    def find_broken_links(self, directory: Path) -> list[Path]:
        """
        Trouve tous les liens symboliques cassés dans un répertoire (récursif).

        Args :
            directory : Répertoire à parcourir

        Retourne :
            Liste des chemins vers les liens symboliques cassés
        """
        ...
