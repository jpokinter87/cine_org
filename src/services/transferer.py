"""
Service de transfert atomique de fichiers avec gestion des conflits.

Ce module fournit les fonctions de transfert de fichiers vers leur
destination finale avec:
- Detection des conflits via hash (doublons vs collisions de noms)
- Deplacement atomique (rollback en cas d'erreur)
- Creation de symlinks relatifs dans video/ vers storage/
"""

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Protocol

from src.infrastructure.persistence.hash_service import compute_file_hash


class ConflictType(Enum):
    """
    Type de conflit detecte lors du transfert.

    NONE: Pas de conflit (fichier destination n'existe pas)
    DUPLICATE: Meme hash - fichier identique existe deja
    NAME_COLLISION: Meme nom mais contenu different
    """

    NONE = "none"
    DUPLICATE = "duplicate"
    NAME_COLLISION = "name_collision"


@dataclass
class ConflictInfo:
    """
    Information sur un conflit de fichier.

    Attributs:
        conflict_type: Type de conflit (DUPLICATE ou NAME_COLLISION)
        existing_path: Chemin du fichier existant en conflit
        existing_hash: Hash du fichier existant
        new_hash: Hash du fichier source
    """

    conflict_type: ConflictType
    existing_path: Path
    existing_hash: str
    new_hash: str


@dataclass
class TransferResult:
    """
    Resultat d'une operation de transfert.

    Attributs:
        success: True si le transfert a reussi
        final_path: Chemin final du fichier (si succes)
        symlink_path: Chemin du symlink cree (si demande)
        conflict: Information sur le conflit (si echec pour conflit)
        error: Message d'erreur (si echec pour autre raison)
    """

    success: bool
    final_path: Optional[Path] = None
    symlink_path: Optional[Path] = None
    conflict: Optional[ConflictInfo] = None
    error: Optional[str] = None


class IAtomicFileSystem(Protocol):
    """
    Interface pour les operations atomiques sur les fichiers.

    Extension de IFileSystem avec atomic_move.
    """

    def exists(self, path: Path) -> bool:
        """Verifie si un chemin existe."""
        ...

    def atomic_move(self, source: Path, destination: Path) -> bool:
        """Deplace un fichier de maniere atomique."""
        ...


class TransfererService:
    """
    Service de transfert atomique de fichiers.

    Gere le transfert de fichiers video vers leur destination finale
    avec detection des conflits, deplacement atomique et creation
    de symlinks relatifs.

    Utilisation:
        transferer = TransfererService(file_system, symlink_manager, storage, video)
        result = transferer.transfer_file(source, destination)
        if result.success:
            print(f"Fichier deplace vers {result.final_path}")
            print(f"Symlink cree: {result.symlink_path}")
        else:
            print(f"Erreur: {result.error or result.conflict}")
    """

    def __init__(
        self,
        file_system: IAtomicFileSystem,
        symlink_manager,  # ISymlinkManager
        storage_dir: Path,
        video_dir: Path,
    ):
        """
        Initialise le service de transfert.

        Args:
            file_system: Adaptateur systeme de fichiers avec atomic_move
            symlink_manager: Gestionnaire de symlinks
            storage_dir: Repertoire racine de stockage physique
            video_dir: Repertoire racine des symlinks (miroir de storage)
        """
        self._fs = file_system
        self._symlinks = symlink_manager
        self._storage_dir = Path(storage_dir)
        self._video_dir = Path(video_dir)

    def check_conflict(
        self, source: Path, destination: Path
    ) -> Optional[ConflictInfo]:
        """
        Verifie s'il y a un conflit avec un fichier existant.

        Compare les hash pour distinguer:
        - DUPLICATE: meme fichier (meme hash)
        - NAME_COLLISION: fichiers differents (hash differents)

        Args:
            source: Chemin du fichier source
            destination: Chemin de destination prevu

        Returns:
            ConflictInfo si conflit, None sinon.
        """
        if not self._fs.exists(destination):
            return None

        # Calculer les hash
        source_hash = compute_file_hash(source)
        dest_hash = compute_file_hash(destination)

        # Determiner le type de conflit
        if source_hash == dest_hash:
            conflict_type = ConflictType.DUPLICATE
        else:
            conflict_type = ConflictType.NAME_COLLISION

        return ConflictInfo(
            conflict_type=conflict_type,
            existing_path=destination,
            existing_hash=dest_hash,
            new_hash=source_hash,
        )

    def transfer_file(
        self,
        source: Path,
        destination: Path,
        create_symlink: bool = True,
        symlink_destination: Optional[Path] = None,
    ) -> TransferResult:
        """
        Transfere un fichier vers sa destination avec atomicite.

        Operations effectuees:
        1. Verification des conflits via hash
        2. Deplacement atomique du fichier
        3. Creation du symlink relatif (optionnel)
        4. Rollback en cas d'erreur

        Args:
            source: Chemin du fichier source
            destination: Chemin de destination dans storage/
            create_symlink: Si True, cree un symlink dans video/
            symlink_destination: Chemin personnalise pour le symlink.
                Si None, utilise le miroir de destination dans video_dir.

        Returns:
            TransferResult avec le resultat de l'operation.
        """
        source = Path(source)
        destination = Path(destination)

        # Etape 1: Verifier les conflits
        conflict = self.check_conflict(source, destination)
        if conflict:
            return TransferResult(success=False, conflict=conflict)

        # Etape 2: Deplacement atomique
        if not self._fs.atomic_move(source, destination):
            return TransferResult(
                success=False, error="Deplacement atomique echoue"
            )

        # Etape 3: Creation du symlink (avec rollback si erreur)
        symlink_path = None
        if create_symlink:
            try:
                if symlink_destination:
                    symlink_path = self._create_custom_symlink(
                        destination, symlink_destination
                    )
                else:
                    symlink_path = self._create_mirror_symlink(destination)
            except Exception as e:
                # Rollback: remettre le fichier a sa position originale
                try:
                    self._fs.atomic_move(destination, source)
                except Exception:
                    pass  # Le rollback peut echouer, on log l'erreur principale
                return TransferResult(success=False, error=str(e))

        return TransferResult(
            success=True,
            final_path=destination,
            symlink_path=symlink_path,
        )

    def _create_mirror_symlink(self, storage_path: Path) -> Path:
        """
        Cree un symlink relatif dans video/ pointant vers storage/.

        Le symlink est cree avec un chemin relatif pour permettre
        la portabilite du systeme (ex: changement de point de montage).

        Args:
            storage_path: Chemin du fichier dans storage/

        Returns:
            Chemin du symlink cree dans video/.

        Raises:
            ValueError: Si le fichier n'est pas sous storage_dir.
            OSError: Si la creation du symlink echoue.
        """
        # Calculer le chemin relatif depuis storage_dir
        try:
            relative_to_storage = storage_path.relative_to(self._storage_dir)
        except ValueError as e:
            raise ValueError(
                f"Le fichier {storage_path} n'est pas sous {self._storage_dir}"
            ) from e

        # Construire le chemin du symlink dans video/
        symlink_path = self._video_dir / relative_to_storage

        return self._create_symlink_at(storage_path, symlink_path)

    def _create_custom_symlink(
        self, storage_path: Path, symlink_path: Path
    ) -> Path:
        """
        Cree un symlink a un emplacement personnalise pointant vers storage.

        Permet une structure de symlinks differente de la structure de stockage
        (ex: series classees par type dans video/ mais pas dans storage/).

        Args:
            storage_path: Chemin du fichier dans storage/
            symlink_path: Chemin complet ou le creer le symlink

        Returns:
            Chemin du symlink cree.
        """
        return self._create_symlink_at(storage_path, symlink_path)

    def _create_symlink_at(self, target_path: Path, symlink_path: Path) -> Path:
        """
        Cree un symlink relatif a l'emplacement specifie.

        Args:
            target_path: Chemin du fichier cible (dans storage/)
            symlink_path: Chemin ou creer le symlink

        Returns:
            Chemin du symlink cree.

        Raises:
            OSError: Si la creation du symlink echoue.
        """
        # Creer les repertoires parents
        symlink_path.parent.mkdir(parents=True, exist_ok=True)

        # Calculer le chemin relatif vers la cible
        # Utilise os.path.relpath pour compatibilite Python 3.11
        # (Path.relative_to avec walk_up=True necessite Python 3.12)
        target_relative = os.path.relpath(target_path, symlink_path.parent)

        # Supprimer le symlink existant s'il y en a un
        if symlink_path.exists() or symlink_path.is_symlink():
            symlink_path.unlink()

        # Creer le symlink
        symlink_path.symlink_to(target_relative)

        return symlink_path
