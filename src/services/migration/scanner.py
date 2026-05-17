"""
Scanner pour la migration depuis d'anciens NAS.

Parcourt l'arborescence de symlinks "source" et produit un MigrationCandidate
par fichier vidéo découvert. Le scanner ne fait aucune décision métier (filtrage
par note, choix de destination) : il extrait l'info brute (cible résolue,
catégorie, taille) et tagge les cas particuliers (lien brisé, fichier déjà
sur destination, fichier physique au lieu de symlink).

Utilisation :
    scanner = MigrationScanner(
        video_extensions=VIDEO_EXTENSIONS,
        destination_root=Path("/media/NAS64"),
        alternative_roots=[Path("/media/usb1/Vidéo_usb1"), ...],
    )
    for candidate in scanner.scan(Path("/media/Serveur/Vidéos")):
        ...
"""

from __future__ import annotations

import os
import unicodedata
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Optional

from src.core.ports.parser import IMediaInfoExtractor
from src.services.migration.dataclasses import MigrationCandidate


# Préfixes par défaut pour limiter le scan aux répertoires de vidéothèque
# pertinents (Films, Séries/Series, Animations/Animes). Insensible à la casse
# et aux accents — match si un segment du chemin commence par un de ces préfixes.
DEFAULT_CATEGORY_PREFIXES: tuple[str, ...] = ("film", "seri", "anim")


def _normalize_segment(value: str) -> str:
    """Normalise un segment de chemin pour comparaison : strip accents + lowercase."""
    nfkd = unicodedata.normalize("NFKD", value)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


class MigrationScanner:
    """
    Walker de l'arborescence source.

    Args:
        video_extensions: Extensions de fichiers à inclure (ex: VIDEO_EXTENSIONS).
        destination_root: Si fourni, sert à détecter les symlinks dont la
            cible est déjà sur le nouveau NAS (bucket already_on_destination).
        alternative_roots: Racines à explorer pour retrouver une cible quand
            un symlink est cassé (le fichier physique a été déplacé sur un
            autre disque).
    """

    def __init__(
        self,
        video_extensions: Iterable[str],
        destination_root: Optional[Path] = None,
        alternative_roots: Optional[Iterable[Path]] = None,
        category_prefixes: Optional[Iterable[str]] = DEFAULT_CATEGORY_PREFIXES,
        media_info_extractor: Optional[IMediaInfoExtractor] = None,
    ) -> None:
        self._video_extensions = frozenset(e.lower() for e in video_extensions)
        self._destination_root = (
            destination_root.resolve() if destination_root else None
        )
        self._alternative_roots = (
            [Path(r) for r in alternative_roots] if alternative_roots else []
        )
        # category_prefixes=None désactive le filtrage (scan tout).
        self._category_prefixes: Optional[tuple[str, ...]] = (
            tuple(_normalize_segment(p) for p in category_prefixes)
            if category_prefixes is not None
            else None
        )
        # Cache des index alt_root -> {filename: full_path} pour éviter de
        # re-scanner les disques de secours à chaque lien cassé.
        self._alt_index_cache: dict[Path, dict[str, Path]] = {}
        # Extracteur mediainfo (optionnel). Quand fourni, le scanner extrait
        # la durée + codecs sur la cible résolue. Utilisé par le matcher
        # mode raw pour discriminer les films homonymes via la durée TMDB.
        self._media_info_extractor = media_info_extractor

    def count_files(self, root: Path) -> int:
        """Compte rapidement les fichiers vidéo matchant les filtres, sans
        extraire les métadonnées ni résoudre les symlinks.

        Utile pour prédimensionner une barre de progression sans payer le
        coût (potentiellement long) de mediainfo sur des milliers de
        fichiers vidéo. La sémantique de filtrage est identique à `scan()`.
        """
        root = Path(root)
        n = 0
        for dirpath, _, filenames in os.walk(root, followlinks=False):
            for name in filenames:
                full = Path(dirpath) / name
                if full.suffix.lower() not in self._video_extensions:
                    continue
                if not self._matches_category(full, root):
                    continue
                n += 1
        return n

    def scan(self, root: Path) -> Iterator[MigrationCandidate]:
        """
        Itère sur tous les fichiers vidéo sous `root` et produit un candidat
        par entrée. Les fichiers d'extension non vidéo sont silencieusement
        ignorés (cas typique : fichiers .nfo, .txt, posters, etc.).

        Si `category_prefixes` est défini, seuls les fichiers dont au moins
        un segment de chemin commence par un de ces préfixes (insensible à
        la casse et aux accents) sont produits. Permet d'ignorer Docs/, TV/,
        Musique/, etc. quand on scanne la racine d'une vidéothèque mixte.
        """
        root = Path(root)
        for dirpath, _, filenames in os.walk(root, followlinks=False):
            for name in filenames:
                full = Path(dirpath) / name
                if full.suffix.lower() not in self._video_extensions:
                    continue
                if not self._matches_category(full, root):
                    continue
                yield self._classify(full, root)

    def _matches_category(self, path: Path, root: Path) -> bool:
        """Vérifie qu'au moins un segment relatif matche la whitelist."""
        if self._category_prefixes is None:
            return True
        try:
            relative = path.relative_to(root)
        except ValueError:
            return True  # Hors source_root : on ne devrait pas arriver ici.
        for segment in relative.parts[:-1]:  # Exclut le filename lui-même.
            normalized = _normalize_segment(segment)
            if any(
                normalized.startswith(prefix)
                for prefix in self._category_prefixes
            ):
                return True
        return False

    def _classify(self, path: Path, root: Path) -> MigrationCandidate:
        media_root, relative_category = self._extract_categories(path, root)

        if not path.is_symlink():
            # Fichier physique sous le root de migration : potentiellement
            # à migrer aussi, mais signalé pour traitement manuel.
            try:
                size = path.stat().st_size
            except OSError:
                size = None
            return MigrationCandidate(
                symlink_path=path,
                target_path=path,
                media_root=media_root,
                relative_category=relative_category,
                size_bytes=size,
                is_broken=False,
                already_on_destination=False,
                is_symlink=False,
                media_info=self._extract_media_info(path),
            )

        # Symlink : tenter de résoudre la cible.
        target = self._resolve_target(path)
        is_broken = target is None
        already_on_destination = bool(
            target
            and self._destination_root
            and self._is_under(target, self._destination_root)
        )
        size: Optional[int] = None
        if target is not None and target.exists():
            try:
                size = target.stat().st_size
            except OSError:
                size = None

        return MigrationCandidate(
            symlink_path=path,
            target_path=target,
            media_root=media_root,
            relative_category=relative_category,
            size_bytes=size,
            is_broken=is_broken,
            already_on_destination=already_on_destination,
            is_symlink=True,
            media_info=self._extract_media_info(target),
        )

    def _extract_media_info(self, target: Optional[Path]):
        """Extrait mediainfo sur la cible si un extracteur est configuré.

        Retourne None silencieusement quand : aucun extracteur configuré,
        target absente ou inexistante. Les erreurs d'extraction sont
        captées par l'extracteur lui-même (qui retourne None).
        """
        if self._media_info_extractor is None:
            return None
        if target is None or not target.exists():
            return None
        return self._media_info_extractor.extract(target)

    def _resolve_target(self, symlink: Path) -> Optional[Path]:
        """Suit le symlink, puis fallback sur la recherche dans alternative_roots."""
        try:
            raw = Path(os.readlink(symlink))
        except OSError:
            return None
        candidate = (
            raw if raw.is_absolute() else (symlink.parent / raw).resolve(strict=False)
        )
        if candidate.exists():
            try:
                return candidate.resolve()
            except OSError:
                return candidate

        # Fallback : chercher par nom de fichier dans les roots alternatifs.
        # Fast-path : essai direct alt_root/<basename> avant le walk indexant
        # toute l'arborescence — évite des millions de stat() quand le fichier
        # est exactement à la racine de l'alt_root.
        for alt in self._alternative_roots:
            shortcut = alt / candidate.name
            if shortcut.exists():
                return shortcut
        # Sinon walk complet (mis en cache pour les appels suivants).
        for alt in self._alternative_roots:
            index = self._index_for(alt)
            found = index.get(candidate.name)
            if found is not None:
                return found
        return None

    def _index_for(self, root: Path) -> dict[str, Path]:
        cached = self._alt_index_cache.get(root)
        if cached is not None:
            return cached
        index: dict[str, Path] = {}
        if root.exists():
            for dirpath, _, filenames in os.walk(root, followlinks=False):
                for name in filenames:
                    # Premier vu gagne (suffisant pour les NAS où les noms
                    # sont uniques par dossier).
                    index.setdefault(name, Path(dirpath) / name)
        self._alt_index_cache[root] = index
        return index

    @staticmethod
    def _extract_categories(path: Path, root: Path) -> tuple[str, str]:
        """
        Retourne (media_root, relative_category).

        media_root = premier segment sous `root` (ex: Films, Series, Animations).
        relative_category = chemin relatif de `path.parent` sous media_root.
        """
        try:
            rel = path.relative_to(root)
        except ValueError:
            return "", ""
        parts = rel.parts
        if len(parts) <= 1:
            # Fichier directement dans root : pas de catégorie
            return "", ""
        media_root = parts[0]
        # parent.relative_to(root / media_root) — exclure le nom du fichier
        category_parts = parts[1:-1]
        return media_root, "/".join(category_parts)

    @staticmethod
    def _is_under(child: Path, parent: Path) -> bool:
        try:
            child.resolve().relative_to(parent)
            return True
        except ValueError:
            return False
