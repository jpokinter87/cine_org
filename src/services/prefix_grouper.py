"""
Service de regroupement par préfixe de titre.

Ce module détecte les fichiers médias partageant un préfixe de titre récurrent
et les regroupe dans des sous-répertoires dédiés.

Exemple : 4 fichiers "American *" dans A-Ami/ → création de A-Ami/American/
"""

import json
import re
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.services.organizer import _is_range_dir
from src.utils.constants import VIDEO_EXTENSIONS
from src.utils.helpers import strip_article

_DEFAULT_CACHE_DIR = Path.home() / ".cineorg"
_CACHE_FILENAME = "regroup_cache.json"


@dataclass
class PrefixGroup:
    """
    Groupe de fichiers partageant un préfixe de titre.

    Attributs :
        parent_dir: Répertoire contenant les fichiers à regrouper.
        prefix: Nom du préfixe (futur nom du sous-répertoire).
        files: Liste des fichiers à déplacer.
    """

    parent_dir: Path
    prefix: str
    files: list[Path] = field(default_factory=list)


def extract_title_from_filename(filename: str) -> str:
    """
    Extrait le titre d'un nom de fichier vidéo.

    Retire l'extension puis prend tout ce qui précède la première
    année entre parenthèses (YYYY).

    Args:
        filename: Nom du fichier (avec extension).

    Returns:
        Titre extrait, ou nom sans extension si pas d'année trouvée.
    """
    if not filename:
        return ""

    # Retirer l'extension
    name = Path(filename).stem

    # Chercher (YYYY) et prendre tout ce qui précède
    match = re.search(r"\(\d{4}\)", name)
    if match:
        title = name[: match.start()].strip()
        return title

    return name


def extract_first_word(title: str) -> str:
    """
    Extrait le premier mot significatif d'un titre.

    Retire l'article initial puis retourne le premier token
    (séparé par espace). Les mots composés avec tiret sont
    conservés comme un seul token (ex: "Au-delà").

    Args:
        title: Titre complet.

    Returns:
        Premier mot significatif, ou chaîne vide.
    """
    if not title:
        return ""

    stripped = strip_article(title).strip()
    if not stripped:
        return ""

    # Premier token séparé par espace
    return stripped.split()[0]


class PrefixGrouperService:
    """
    Service de détection et exécution du regroupement par préfixe.

    Méthodes :
        analyze: Détecte les groupes de préfixes récurrents.
        execute: Crée les sous-répertoires et déplace les fichiers.
    """

    def analyze(self, video_dir: Path, min_count: int = 3) -> list[PrefixGroup]:
        """
        Analyse un répertoire vidéo et détecte les préfixes récurrents.

        Scan récursif des répertoires feuilles (contenant des fichiers médias),
        extraction des premiers mots, regroupement et filtrage.

        Args:
            video_dir: Répertoire racine à analyser.
            min_count: Nombre minimum de fichiers pour former un groupe.

        Returns:
            Liste des groupes de préfixes détectés.
        """
        groups: list[PrefixGroup] = []

        # Trouver tous les répertoires contenant des fichiers médias
        leaf_dirs = self._find_leaf_dirs(video_dir)

        for leaf_dir in leaf_dirs:
            dir_groups = self._analyze_directory(leaf_dir, min_count)
            groups.extend(dir_groups)

        return groups

    def execute(
        self,
        groups: list[PrefixGroup],
        video_dir: Path,
        storage_dir: Path,
        progress_callback: "Callable[[str, int], None] | None" = None,
    ) -> int:
        """
        Exécute le regroupement : crée les répertoires et déplace les fichiers.

        Pour chaque groupe, crée un sous-répertoire préfixe et déplace les symlinks.
        Seuls les symlinks sont déplacés ; les fichiers de stockage (NAS) ne sont
        jamais touchés.

        Args:
            groups: Liste des groupes à exécuter.
            video_dir: Répertoire racine des symlinks.
            storage_dir: Répertoire racine de stockage (non modifié).
            progress_callback: Callback(prefix, files_moved) appelé après chaque groupe.

        Returns:
            Nombre total de fichiers déplacés.
        """
        total_moved = 0

        for group in groups:
            # Calculer le chemin relatif du parent par rapport à video_dir
            try:
                rel_path = group.parent_dir.relative_to(video_dir)
            except ValueError:
                continue

            # Créer le sous-répertoire préfixe dans video
            video_prefix_dir = video_dir / rel_path / group.prefix
            video_prefix_dir.mkdir(parents=True, exist_ok=True)

            for video_file in group.files:
                filename = video_file.name

                if video_file.is_symlink():
                    # Résoudre la cible du symlink en chemin absolu
                    original_target = video_file.resolve()

                    # Supprimer l'ancien symlink et créer le nouveau
                    # pointant vers la même cible de stockage (chemin absolu)
                    video_file.unlink()
                    new_link = video_prefix_dir / filename
                    new_link.symlink_to(original_target)

                elif video_file.exists():
                    # Fichier régulier : déplacer directement
                    shutil.move(str(video_file), str(video_prefix_dir / filename))
                else:
                    continue

                total_moved += 1

            if progress_callback:
                progress_callback(group.prefix, len(group.files))

        return total_moved

    def _find_leaf_dirs(self, root: Path) -> list[Path]:
        """
        Trouve les répertoires feuilles contenant des fichiers médias.

        Un répertoire feuille est un répertoire qui contient directement
        des fichiers vidéo (pas uniquement des sous-répertoires).

        Args:
            root: Répertoire racine à explorer.

        Returns:
            Liste des répertoires feuilles.
        """
        leaf_dirs: list[Path] = []

        if not root.exists():
            return leaf_dirs

        for dirpath in sorted(root.rglob("*")):
            if not dirpath.is_dir():
                continue
            # Vérifier que ce répertoire contient des fichiers médias
            has_media = any(
                f.suffix.lower() in VIDEO_EXTENSIONS
                for f in dirpath.iterdir()
                if f.is_file() or f.is_symlink()
            )
            if has_media:
                leaf_dirs.append(dirpath)

        return leaf_dirs

    def _is_prefix_dir(self, directory: Path) -> bool:
        """
        Vérifie si un répertoire est déjà un sous-répertoire de préfixe.

        Un répertoire préfixe est un répertoire dont le nom n'est ni
        une lettre simple, ni une plage alphabétique, et qui contient
        des fichiers médias correspondant à son nom.

        Args:
            directory: Répertoire à vérifier.

        Returns:
            True si c'est un répertoire de préfixe existant.
        """
        name = directory.name
        # Lettre simple ou plage → pas un préfixe
        if len(name) <= 1 or _is_range_dir(name):
            return False
        # Vérifier que les fichiers médias commencent par le nom du répertoire
        for f in directory.iterdir():
            if f.is_file() or f.is_symlink():
                if f.suffix.lower() in VIDEO_EXTENSIONS:
                    title = extract_title_from_filename(f.name)
                    first_word = extract_first_word(title)
                    if first_word and first_word.lower().startswith(name.lower()):
                        return True
        return False

    def _analyze_directory(
        self, directory: Path, min_count: int
    ) -> list[PrefixGroup]:
        """
        Analyse un répertoire et détecte les groupes de préfixes.

        Args:
            directory: Répertoire à analyser.
            min_count: Seuil minimum de fichiers par groupe.

        Returns:
            Liste des groupes détectés dans ce répertoire.
        """
        # Ne pas analyser les répertoires qui sont déjà des préfixes
        if self._is_prefix_dir(directory):
            return []
        # Collecter les fichiers médias et leurs premiers mots
        word_to_files: dict[str, list[Path]] = {}

        for f in sorted(directory.iterdir()):
            if not (f.is_file() or f.is_symlink()):
                continue
            if f.suffix.lower() not in VIDEO_EXTENSIONS:
                continue

            title = extract_title_from_filename(f.name)
            first_word = extract_first_word(title)
            if not first_word:
                continue

            key = first_word.lower()
            word_to_files.setdefault(key, []).append(f)

        # Fusionner les groupes dont les clés partagent un préfixe >= 4 chars
        merged = self._merge_groups(word_to_files)

        # Collecter les noms d'ancêtres (strippés d'article) pour détecter la redondance
        ancestor_words = set()
        for parent in [directory] + list(directory.parents):
            name = parent.name
            if name:
                stripped_name = strip_article(name).strip()
                if stripped_name:
                    first_word = stripped_name.split()[0].lower()
                    ancestor_words.add(first_word)

        # Filtrer par seuil et construire les PrefixGroup
        groups: list[PrefixGroup] = []
        for prefix, files in sorted(merged.items()):
            if len(files) >= min_count:
                # Exclure si le préfixe est redondant avec un répertoire ancêtre
                if prefix.lower() in ancestor_words:
                    continue
                groups.append(PrefixGroup(
                    parent_dir=directory,
                    prefix=prefix,
                    files=files,
                ))

        return groups

    def _merge_groups(
        self, word_to_files: dict[str, list[Path]]
    ) -> dict[str, list[Path]]:
        """
        Fusionne les groupes dont les clés partagent un préfixe >= 4 caractères.

        Par exemple : "amant" + "amants" + "amante" → "amant" (plus court).
        Le nom du répertoire utilise la casse originale du préfixe le plus court.

        Args:
            word_to_files: Mapping clé lowercase → fichiers.

        Returns:
            Mapping préfixe fusionné (casse originale) → fichiers.
        """
        if not word_to_files:
            return {}

        # Trier les clés par longueur (plus courte d'abord) puis alphabétiquement
        sorted_keys = sorted(word_to_files.keys(), key=lambda k: (len(k), k))

        # Pour chaque clé, chercher si elle est un préfixe d'une autre
        merged: dict[str, list[Path]] = {}
        key_to_merged: dict[str, str] = {}  # mapping clé originale -> clé fusionnée

        for key in sorted_keys:
            # Chercher si cette clé commence par une clé déjà fusionnée
            found_parent = None
            for merged_key in list(merged.keys()):
                merged_lower = merged_key.lower()
                if len(merged_lower) >= 4 and key.startswith(merged_lower):
                    found_parent = merged_key
                    break

            if found_parent is not None:
                # Fusionner dans le groupe parent
                merged[found_parent].extend(word_to_files[key])
                key_to_merged[key] = found_parent
            else:
                # Nouveau groupe - utiliser la casse du premier mot trouvé
                original_word = extract_first_word(
                    extract_title_from_filename(word_to_files[key][0].name)
                )
                merged[original_word] = list(word_to_files[key])
                key_to_merged[key] = original_word

        return merged


def save_regroup_cache(
    video_dir: Path,
    storage_dir: Path,
    groups: list[PrefixGroup],
    cache_dir: Optional[Path] = None,
) -> None:
    """
    Sauvegarde l'analyse regroup en cache JSON.

    Args:
        video_dir: Répertoire vidéo analysé.
        storage_dir: Répertoire storage correspondant.
        groups: Groupes détectés.
        cache_dir: Répertoire du cache (défaut: ~/.cineorg).
    """
    cache_dir = cache_dir or _DEFAULT_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / _CACHE_FILENAME

    data = {
        "video_dir": str(video_dir),
        "storage_dir": str(storage_dir),
        "timestamp": time.time(),
        "groups": [
            {
                "parent_dir": str(g.parent_dir),
                "prefix": g.prefix,
                "files": [str(f) for f in g.files],
            }
            for g in groups
        ],
    }

    cache_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def load_regroup_cache(
    max_age_minutes: int = 10,
    cache_dir: Optional[Path] = None,
) -> Optional[tuple[Path, Path, list[PrefixGroup]]]:
    """
    Charge le cache regroup s'il existe et est récent.

    Args:
        max_age_minutes: Age maximum du cache en minutes.
        cache_dir: Répertoire du cache (défaut: ~/.cineorg).

    Returns:
        Tuple (video_dir, storage_dir, groups) si cache valide, None sinon.
    """
    cache_dir = cache_dir or _DEFAULT_CACHE_DIR
    cache_file = cache_dir / _CACHE_FILENAME

    if not cache_file.exists():
        return None

    try:
        data = json.loads(cache_file.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    # Vérifier l'âge du cache
    age_seconds = time.time() - data.get("timestamp", 0)
    if age_seconds > max_age_minutes * 60:
        return None

    # Reconstruire les PrefixGroup
    video_dir = Path(data["video_dir"])
    storage_dir = Path(data["storage_dir"])
    groups = []
    for g in data.get("groups", []):
        groups.append(PrefixGroup(
            parent_dir=Path(g["parent_dir"]),
            prefix=g["prefix"],
            files=[Path(f) for f in g["files"]],
        ))

    return video_dir, storage_dir, groups
