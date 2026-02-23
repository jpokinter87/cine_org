"""
Service de transfert atomique de fichiers avec gestion des conflits.

Ce module fournit les fonctions de transfert de fichiers vers leur
destination finale avec:
- Detection des conflits via hash (doublons vs collisions de noms)
- Deplacement atomique (rollback en cas d'erreur)
- Creation de symlinks absolus dans video/ vers storage/
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, Protocol

from src.infrastructure.persistence.hash_service import compute_file_hash
from src.utils.constants import VIDEO_EXTENSIONS


class ConflictType(Enum):
    """
    Type de conflit detecte lors du transfert.

    NONE: Pas de conflit (fichier destination n'existe pas)
    DUPLICATE: Meme hash - fichier identique existe deja
    NAME_COLLISION: Meme nom mais contenu different
    SIMILAR_CONTENT: Contenu similaire existe (ex: serie sans annee vs avec annee)
    """

    NONE = "none"
    DUPLICATE = "duplicate"
    NAME_COLLISION = "name_collision"
    SIMILAR_CONTENT = "similar_content"


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
class ExistingFileInfo:
    """
    Information sur un fichier existant pour comparaison.

    Attributs:
        path: Chemin du fichier
        size_bytes: Taille en octets
        resolution: Resolution video (ex: "1080p", "4K")
        video_codec: Codec video (ex: "HEVC", "H.264")
        audio_codec: Codec audio principal (ex: "DTS-HD", "AAC")
        duration_seconds: Duree en secondes
    """

    path: Path
    size_bytes: int
    resolution: Optional[str] = None
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    duration_seconds: Optional[int] = None


@dataclass
class SimilarContentInfo:
    """
    Information sur un conflit de contenu similaire.

    Utilise pour les cas ou un film/serie existe deja avec un nom
    legerement different (ex: "Station Eleven" vs "Station Eleven (2021)").

    Attributs:
        existing_dir: Repertoire existant similaire
        existing_files: Liste des fichiers existants avec leurs infos
        new_title: Titre du nouveau contenu
        existing_title: Titre du contenu existant
        similarity_reason: Raison de la similarite detectee
    """

    existing_dir: Path
    existing_files: list[ExistingFileInfo]
    new_title: str
    existing_title: str
    similarity_reason: str


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

        # Supprimer le symlink existant s'il y en a un
        if symlink_path.exists() or symlink_path.is_symlink():
            symlink_path.unlink()

        # Creer le symlink avec un chemin absolu vers la cible
        symlink_path.symlink_to(target_path.resolve())

        return symlink_path

    def find_similar_content(
        self,
        title: str,
        year: Optional[int],
        destination_dir: Path,
        is_series: bool = False,
    ) -> Optional[SimilarContentInfo]:
        """
        Recherche un contenu similaire dans le repertoire de destination.

        Detecte les cas ou un film/serie existe deja avec un nom similaire:
        - "Station Eleven" vs "Station Eleven (2021)"
        - "Matrix" vs "The Matrix (1999)"

        Args:
            title: Titre du nouveau contenu
            year: Annee du nouveau contenu (peut etre None)
            destination_dir: Repertoire de destination (parent du dossier cible)
            is_series: True si c'est une serie, False pour un film

        Returns:
            SimilarContentInfo si un contenu similaire existe, None sinon.
        """
        if not destination_dir.exists():
            return None

        # Normaliser le titre pour comparaison
        normalized_title = self._normalize_title(title)

        # Chercher dans les sous-repertoires
        for subdir in destination_dir.iterdir():
            if not subdir.is_dir():
                continue

            # Extraire le titre existant (sans annee)
            existing_name = subdir.name
            existing_title, existing_year = self._extract_title_year(existing_name)
            normalized_existing = self._normalize_title(existing_title)

            # Verifier la similarite
            if normalized_title == normalized_existing:
                # Meme titre, verifier si c'est vraiment different
                new_name = f"{title} ({year})" if year else title

                if existing_name != new_name:
                    # Conflit detecte: meme titre mais noms differents
                    files_info = self._collect_files_info(subdir, is_series)
                    reason = self._get_similarity_reason(
                        existing_name, new_name, existing_year, year
                    )

                    return SimilarContentInfo(
                        existing_dir=subdir,
                        existing_files=files_info,
                        new_title=new_name,
                        existing_title=existing_name,
                        similarity_reason=reason,
                    )
                else:
                    # Nom identique: contenu existant avec le meme nom
                    # Signaler pour eviter les doublons d'episodes/fichiers
                    files_info = self._collect_files_info(subdir, is_series)
                    if files_info:  # Seulement si des fichiers existent deja
                        return SimilarContentInfo(
                            existing_dir=subdir,
                            existing_files=files_info,
                            new_title=new_name,
                            existing_title=existing_name,
                            similarity_reason="Contenu existant avec le meme nom",
                        )

        return None

    def _normalize_title(self, title: str) -> str:
        """Normalise un titre pour comparaison (minuscules, sans articles)."""
        # Retirer les articles courants
        articles = ["le", "la", "les", "l'", "the", "a", "an"]
        words = title.lower().split()
        if words and words[0] in articles:
            words = words[1:]
        return " ".join(words)

    def _extract_title_year(self, name: str) -> tuple[str, Optional[int]]:
        """Extrait le titre et l'annee d'un nom de dossier."""
        # Pattern: "Titre (YYYY)" ou juste "Titre"
        match = re.match(r"^(.+?)\s*\((\d{4})\)$", name)
        if match:
            return match.group(1).strip(), int(match.group(2))
        return name, None

    def _get_similarity_reason(
        self,
        existing_name: str,
        new_name: str,
        existing_year: Optional[int],
        new_year: Optional[int],
    ) -> str:
        """Determine la raison de la similarite."""
        if existing_year is None and new_year is not None:
            return f"L'existant n'a pas d'annee, le nouveau a ({new_year})"
        elif existing_year is not None and new_year is None:
            return f"L'existant a une annee ({existing_year}), le nouveau n'en a pas"
        elif existing_year != new_year:
            return f"Annees differentes: existant ({existing_year}) vs nouveau ({new_year})"
        else:
            return f"Noms differents: '{existing_name}' vs '{new_name}'"

    def _collect_files_info(
        self, directory: Path, is_series: bool
    ) -> list[ExistingFileInfo]:
        """
        Collecte les informations sur les fichiers video dans un repertoire.

        Args:
            directory: Repertoire a scanner
            is_series: Si True, cherche recursivement dans les saisons

        Returns:
            Liste des informations de fichiers.
        """
        files_info = []

        # Pour les series, parcourir les saisons
        if is_series:
            for item in directory.rglob("*"):
                if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS:
                    files_info.append(self._get_file_info(item))
        else:
            # Pour les films, chercher dans le repertoire courant ou parent
            for item in directory.iterdir():
                if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS:
                    files_info.append(self._get_file_info(item))

        return files_info

    def _get_file_info(self, file_path: Path) -> ExistingFileInfo:
        """Extrait les informations techniques d'un fichier video."""
        from src.adapters.parsing.mediainfo_extractor import MediaInfoExtractor

        size = file_path.stat().st_size if file_path.exists() else 0

        # Extraire les infos media
        resolution = None
        video_codec = None
        audio_codec = None
        duration = None

        try:
            extractor = MediaInfoExtractor()
            media_info = extractor.extract(file_path)
            if media_info:
                if media_info.resolution:
                    resolution = media_info.resolution.label
                if media_info.video_codec:
                    video_codec = media_info.video_codec.name
                if media_info.audio_codecs:
                    audio_codec = media_info.audio_codecs[0].name
                duration = media_info.duration_seconds
        except Exception:
            pass  # Infos non disponibles

        return ExistingFileInfo(
            path=file_path,
            size_bytes=size,
            resolution=resolution,
            video_codec=video_codec,
            audio_codec=audio_codec,
            duration_seconds=duration,
        )

    def move_to_staging(
        self,
        path: Path,
        staging_dir: Path,
        preserve_structure: bool = True,
    ) -> Path:
        """
        Deplace un fichier ou repertoire vers la zone d'attente.

        Args:
            path: Chemin du fichier ou repertoire a deplacer
            staging_dir: Repertoire racine de la zone d'attente
            preserve_structure: Si True, preserve la structure relative

        Returns:
            Chemin de destination dans la zone d'attente.
        """
        staging_dir.mkdir(parents=True, exist_ok=True)

        if preserve_structure:
            # Essayer de preserver la structure relative
            try:
                if str(path).startswith(str(self._storage_dir)):
                    relative = path.relative_to(self._storage_dir)
                    dest = staging_dir / relative
                elif str(path).startswith(str(self._video_dir)):
                    relative = path.relative_to(self._video_dir)
                    dest = staging_dir / relative
                else:
                    dest = staging_dir / path.name
            except ValueError:
                dest = staging_dir / path.name
        else:
            dest = staging_dir / path.name

        # Creer les parents et deplacer
        dest.parent.mkdir(parents=True, exist_ok=True)

        if path.is_dir():
            import shutil
            shutil.move(str(path), str(dest))
        else:
            self._fs.atomic_move(path, dest)

        return dest
