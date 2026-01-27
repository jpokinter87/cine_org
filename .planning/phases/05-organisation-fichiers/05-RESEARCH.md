# Phase 5: Organisation Fichiers - Research

**Researched:** 2026-01-27
**Domain:** File Operations, Symlink Management, Filename Sanitization, Directory Organization, Quality Scoring
**Confidence:** HIGH

## Summary

Cette phase implemente le renommage des fichiers video selon un format standardise et leur organisation dans une structure de repertoires avec symlinks. Les operations principales sont : sanitisation des noms de fichiers (caracteres speciaux, ligatures), creation de la structure de repertoires avec subdivision dynamique, deplacement des fichiers physiques vers `stockage/`, et creation des symlinks relatifs dans `video/`.

Le projet dispose deja de l'architecture hexagonale necessaire avec les ports `IFileSystem` et `ISymlinkManager`, ainsi que le service de hash xxhash par echantillons. La bibliotheque standard Python (`pathlib`, `os`, `shutil`) fournit toutes les primitives necessaires. La bibliotheque `pathvalidate` peut etre utilisee pour la sanitisation cross-platform des noms de fichiers. Les operations atomiques sur meme filesystem utilisent `os.replace()`, tandis que les moves cross-filesystem necessitent un pattern staged copy.

**Primary recommendation:** Utiliser les ports existants `IFileSystem` et `ISymlinkManager`, etendre `FileSystemAdapter` avec les operations atomiques, implementer un `RenamerService` pour la generation des noms et un `OrganizerService` pour la structure des repertoires. La sanitisation se fait via `pathvalidate` + remplacement manuel des ligatures francaises.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pathlib | stdlib | Operations chemins | Standard Python, cross-platform, immutable paths |
| pathvalidate | 3.2+ | Sanitisation noms fichiers | Cross-platform, Unicode support, configurable |
| xxhash | 3.6+ | Hash rapide pour doublons | Deja utilise (hash_service.py), 10x plus rapide que SHA |
| unicodedata | stdlib | Normalisation Unicode | Standard pour ligatures et caracteres speciaux |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| os | stdlib | Operations bas niveau (replace, symlink) | Atomicite sur meme filesystem |
| shutil | stdlib | Copy cross-filesystem | Quand source/dest sur filesystems differents |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| pathvalidate | sanitize-filename | Moins de fonctionnalites, pas de platform targeting |
| pathvalidate | Regex manuel | Plus de controle mais erreurs sur edge cases |
| os.replace | shutil.move | shutil fallback silencieusement vers non-atomique |

**Installation:**
```bash
pip install pathvalidate
```

## Architecture Patterns

### Recommended Project Structure

```
src/
├── core/
│   ├── ports/
│   │   └── file_system.py      # Existant: IFileSystem, ISymlinkManager
│   └── value_objects/
│       └── media_info.py       # Existant: Resolution, VideoCodec, AudioCodec
├── services/
│   ├── renamer.py              # NOUVEAU: Generation noms standardises
│   ├── organizer.py            # NOUVEAU: Structure repertoires + subdivision
│   └── transferer.py           # NOUVEAU: Move + symlink avec rollback
├── adapters/
│   └── file_system.py          # Existant: FileSystemAdapter
└── infrastructure/
    └── persistence/
        └── hash_service.py     # Existant: compute_file_hash (xxhash)
```

### Pattern 1: Service Renamer (Pure Function)

**What:** Service de generation de noms de fichiers standardises sans effet de bord
**When to use:** Pour generer le nom cible avant toute operation de deplacement

```python
# File: src/services/renamer.py
import re
import unicodedata
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from pathvalidate import sanitize_filename

from src.core.entities.media import Movie, Series, Episode
from src.core.value_objects import MediaInfo

# Caracteres a remplacer par tiret
SPECIAL_CHARS_TO_DASH = r'[:\\/*"<>|]'
# Point d'interrogation -> points de suspension
QUESTION_MARK = r'\?'

# Longueur maximale du nom (hors extension)
MAX_FILENAME_LENGTH = 200


def normalize_ligatures(text: str) -> str:
    """Normalise les ligatures francaises."""
    replacements = {
        '\u0153': 'oe',  # oe
        '\u0152': 'Oe',  # OE
        '\u00e6': 'ae',  # ae
        '\u00c6': 'Ae',  # AE
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    return text


def sanitize_for_filesystem(text: str) -> str:
    """
    Sanitise un texte pour utilisation comme nom de fichier.

    Applique dans l'ordre :
    1. Normalisation NFKC Unicode
    2. Remplacement ligatures francaises
    3. Remplacement caracteres speciaux par tiret
    4. Remplacement ? par ...
    5. Sanitisation cross-platform via pathvalidate
    """
    # Normalisation Unicode
    text = unicodedata.normalize('NFKC', text)

    # Ligatures francaises
    text = normalize_ligatures(text)

    # Caracteres speciaux -> tiret
    text = re.sub(SPECIAL_CHARS_TO_DASH, '-', text)

    # ? -> ...
    text = re.sub(QUESTION_MARK, '...', text)

    # Sanitisation cross-platform
    text = sanitize_filename(text, platform='universal')

    return text


def format_language_code(languages: tuple[str, ...]) -> str:
    """Formate les codes langue pour le nom de fichier."""
    if not languages:
        return ""
    if len(languages) > 1:
        return "MULTi"
    # Code ISO court en majuscules
    return languages[0].upper()[:2]


@dataclass(frozen=True)
class RenameResult:
    """Resultat du calcul de renommage."""
    new_name: str
    new_path: Path


def generate_movie_filename(
    movie: Movie,
    media_info: MediaInfo,
    extension: str,
) -> str:
    """
    Genere le nom de fichier pour un film.

    Format: Titre (Annee) Langue Codec Resolution.ext
    """
    parts = []

    # Titre sanitise
    title = sanitize_for_filesystem(movie.title)
    parts.append(title)

    # Annee
    if movie.year:
        parts.append(f"({movie.year})")

    # Langue
    if media_info and media_info.audio_languages:
        lang_codes = tuple(lang.code for lang in media_info.audio_languages)
        lang = format_language_code(lang_codes)
        if lang:
            parts.append(lang)

    # Codec video
    if media_info and media_info.video_codec:
        parts.append(media_info.video_codec.name)

    # Resolution
    if media_info and media_info.resolution:
        parts.append(media_info.resolution.label)

    # Assemblage
    filename = " ".join(parts)

    # Troncature si necessaire
    if len(filename) > MAX_FILENAME_LENGTH:
        filename = filename[:MAX_FILENAME_LENGTH].rstrip()

    return f"{filename}{extension}"
```

### Pattern 2: Service Organizer avec Subdivision Dynamique

**What:** Service de calcul des chemins de destination avec subdivision alphabetique
**When to use:** Pour determiner le repertoire cible avant deplacement

```python
# File: src/services/organizer.py
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from src.core.entities.media import Movie, Series
from src.core.value_objects.parsed_info import MediaType
from src.utils.constants import IGNORED_ARTICLES, GENRE_HIERARCHY

# Seuil de subdivision
MAX_FILES_PER_SUBDIR = 50


def get_sort_letter(title: str) -> str:
    """
    Extrait la lettre de tri en ignorant les articles.

    "Le Parrain" -> "P"
    "The Matrix" -> "M"
    "2001 A Space Odyssey" -> "#"
    """
    # Normaliser et split
    words = title.strip().split()
    if not words:
        return "#"

    # Ignorer article initial
    first_word = words[0].lower().rstrip("'")
    if first_word in IGNORED_ARTICLES and len(words) > 1:
        words = words[1:]

    # Premier caractere significatif
    first_char = words[0][0].upper() if words else "#"

    # Numerique -> #
    if first_char.isdigit():
        return "#"

    return first_char if first_char.isalpha() else "#"


@dataclass
class SubdivisionRange:
    """Plage alphabetique pour une subdivision."""
    start: str
    end: str

    @property
    def label(self) -> str:
        """Label du dossier (ex: A-C, Ab-Am)."""
        if self.start == self.end:
            return self.start
        return f"{self.start}-{self.end}"


def calculate_subdivision(
    existing_items: list[str],
    new_item: str,
    max_per_subdir: int = MAX_FILES_PER_SUBDIR,
) -> SubdivisionRange:
    """
    Calcule la subdivision appropriee pour un nouvel element.

    Algorithme adaptatif :
    - Si < max_per_subdir dans la lettre : pas de subdivision
    - Sinon : subdivise en plages (A-C, D-F) puis plus finement si necessaire
    """
    # Tri par premiere lettre
    first_letter = get_sort_letter(new_item)

    # Compter les elements avec meme lettre initiale
    same_letter_items = [
        item for item in existing_items
        if get_sort_letter(item) == first_letter
    ]

    if len(same_letter_items) < max_per_subdir:
        # Pas besoin de subdivision
        return SubdivisionRange(first_letter, first_letter)

    # Subdivision necessaire - calcul de la plage
    # Trier tous les elements
    all_items = sorted(same_letter_items + [new_item], key=str.lower)

    # Trouver la position du nouvel element
    position = all_items.index(new_item)

    # Calculer l'index de subdivision
    subdir_index = position // max_per_subdir
    start_index = subdir_index * max_per_subdir
    end_index = min(start_index + max_per_subdir - 1, len(all_items) - 1)

    # Determiner les bornes de la plage
    start_prefix = all_items[start_index][:2] if all_items[start_index] else first_letter
    end_prefix = all_items[end_index][:2] if all_items[end_index] else first_letter

    return SubdivisionRange(start_prefix.capitalize(), end_prefix.capitalize())


def get_movie_destination(
    movie: Movie,
    storage_dir: Path,
    existing_files: list[str],
) -> Path:
    """
    Calcule le chemin de destination pour un film.

    Structure: stockage/Films/Genre/Lettre/[Subdivision]/
    """
    # Genre prioritaire
    genre = movie.genres[0] if movie.genres else "Divers"

    # Lettre de tri
    letter = get_sort_letter(movie.title)

    # Subdivision si necessaire
    subdivision = calculate_subdivision(existing_files, movie.title)

    # Construction du chemin
    path = storage_dir / "Films" / genre / letter
    if subdivision.start != subdivision.end:
        path = path / subdivision.label

    return path


def get_series_destination(
    series: Series,
    season_number: int,
    storage_dir: Path,
) -> Path:
    """
    Calcule le chemin de destination pour un episode.

    Structure: stockage/Series/Lettre/[Subdivision]/Titre (Annee)/Saison XX/
    """
    # Lettre de tri
    letter = get_sort_letter(series.title)

    # Nom du dossier serie
    series_folder = f"{series.title}"
    if series.year:
        series_folder += f" ({series.year})"

    # Saison formatee
    season_folder = f"Saison {season_number:02d}"

    return storage_dir / "Series" / letter / series_folder / season_folder
```

### Pattern 3: Transferer avec Rollback

**What:** Service de transfert atomique avec gestion des conflits et rollback
**When to use:** Pour deplacer fichiers et creer symlinks de maniere transactionnelle

```python
# File: src/services/transferer.py
import os
import uuid
import shutil
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Protocol

from src.core.ports.file_system import IFileSystem, ISymlinkManager
from src.infrastructure.persistence.hash_service import compute_file_hash


class ConflictType(Enum):
    """Type de conflit detecte."""
    NONE = "none"
    DUPLICATE = "duplicate"  # Meme hash
    NAME_COLLISION = "name_collision"  # Meme nom, hash different


@dataclass
class ConflictInfo:
    """Information sur un conflit de fichier."""
    conflict_type: ConflictType
    existing_path: Path
    existing_hash: str
    new_hash: str


@dataclass
class TransferOperation:
    """Operation de transfert a effectuer."""
    source: Path
    destination: Path
    symlink_path: Optional[Path] = None
    completed: bool = False


@dataclass
class TransferResult:
    """Resultat d'une operation de transfert."""
    success: bool
    final_path: Optional[Path] = None
    symlink_path: Optional[Path] = None
    conflict: Optional[ConflictInfo] = None
    error: Optional[str] = None


class TransferService:
    """
    Service de transfert de fichiers avec atomicite et rollback.

    Garanties :
    - Atomicite sur meme filesystem via os.replace
    - Staged copy pour cross-filesystem
    - Rollback automatique en cas d'erreur
    - Detection des conflits via hash
    """

    def __init__(
        self,
        file_system: IFileSystem,
        symlink_manager: ISymlinkManager,
        storage_dir: Path,
        video_dir: Path,
    ):
        self._fs = file_system
        self._symlinks = symlink_manager
        self._storage_dir = storage_dir
        self._video_dir = video_dir
        self._pending_operations: list[TransferOperation] = []

    def check_conflict(
        self,
        source: Path,
        destination: Path,
    ) -> Optional[ConflictInfo]:
        """Verifie s'il y a un conflit avec un fichier existant."""
        if not self._fs.exists(destination):
            return None

        source_hash = compute_file_hash(source)
        dest_hash = compute_file_hash(destination)

        if source_hash == dest_hash:
            return ConflictInfo(
                conflict_type=ConflictType.DUPLICATE,
                existing_path=destination,
                existing_hash=dest_hash,
                new_hash=source_hash,
            )
        else:
            return ConflictInfo(
                conflict_type=ConflictType.NAME_COLLISION,
                existing_path=destination,
                existing_hash=dest_hash,
                new_hash=source_hash,
            )

    def transfer_atomic(
        self,
        source: Path,
        destination: Path,
        create_symlink: bool = True,
    ) -> TransferResult:
        """
        Transfere un fichier de maniere atomique.

        1. Verifie les conflits
        2. Cree les repertoires parents
        3. Deplace le fichier (atomique si meme FS)
        4. Cree le symlink si demande
        5. Rollback en cas d'erreur
        """
        # Verification conflit
        conflict = self.check_conflict(source, destination)
        if conflict:
            return TransferResult(
                success=False,
                conflict=conflict,
            )

        # Creer repertoire destination
        destination.parent.mkdir(parents=True, exist_ok=True)

        try:
            # Tentative de rename atomique
            # os.replace est atomique sur meme filesystem
            try:
                os.replace(source, destination)
            except OSError:
                # Cross-filesystem : staged copy
                temp_dest = destination.with_name(f".tmp_{uuid.uuid4().hex}_{destination.name}")
                shutil.copy2(source, temp_dest)
                os.replace(temp_dest, destination)
                source.unlink()

            # Creation symlink
            symlink_path = None
            if create_symlink:
                symlink_path = self._create_mirror_symlink(destination)

            return TransferResult(
                success=True,
                final_path=destination,
                symlink_path=symlink_path,
            )

        except Exception as e:
            # Rollback : si le fichier a ete deplace, le remettre
            if not source.exists() and destination.exists():
                try:
                    os.replace(destination, source)
                except Exception:
                    pass  # Echec du rollback, situation critique
            return TransferResult(
                success=False,
                error=str(e),
            )

    def _create_mirror_symlink(self, storage_path: Path) -> Path:
        """
        Cree un symlink dans video/ qui pointe vers storage_path.

        Structure miroir : video/ reproduit l'arborescence de stockage/
        Chemin relatif pour portabilite.
        """
        # Calculer le chemin relatif dans la structure
        relative_to_storage = storage_path.relative_to(self._storage_dir)
        symlink_path = self._video_dir / relative_to_storage

        # Creer repertoire parent
        symlink_path.parent.mkdir(parents=True, exist_ok=True)

        # Calculer chemin relatif du symlink vers la cible
        # walk_up=True permet de remonter avec ..
        target_relative = storage_path.relative_to(
            symlink_path.parent.resolve(),
            walk_up=True,
        )

        # Creer symlink
        if symlink_path.exists() or symlink_path.is_symlink():
            symlink_path.unlink()
        symlink_path.symlink_to(target_relative)

        return symlink_path
```

### Pattern 4: Quality Scoring pour Comparaison de Doublons

**What:** Algorithme de scoring multi-criteres pour comparer la qualite video
**When to use:** Lors d'un conflit avec hash different pour suggerer le meilleur fichier

```python
# File: src/services/quality_scorer.py
from dataclasses import dataclass
from typing import Optional

from src.core.value_objects import MediaInfo, Resolution, VideoCodec, AudioCodec


@dataclass(frozen=True)
class QualityScore:
    """Score de qualite detaille d'un fichier video."""
    resolution_score: float  # 0-100, poids 30%
    video_codec_score: float  # 0-100, poids 25%
    bitrate_score: float  # 0-100, poids 20%
    audio_score: float  # 0-100, poids 15%
    size_efficiency: float  # 0-100, poids 10%
    total: float  # Score pondere final

    @property
    def breakdown(self) -> str:
        """Description lisible du score."""
        return (
            f"Resolution: {self.resolution_score:.0f}/100 (30%)\n"
            f"Codec video: {self.video_codec_score:.0f}/100 (25%)\n"
            f"Debit video: {self.bitrate_score:.0f}/100 (20%)\n"
            f"Audio: {self.audio_score:.0f}/100 (15%)\n"
            f"Efficacite: {self.size_efficiency:.0f}/100 (10%)\n"
            f"---\n"
            f"TOTAL: {self.total:.0f}/100"
        )


# Ranking des resolutions (hauteur -> score)
RESOLUTION_SCORES = {
    2160: 100,  # 4K
    1080: 75,   # Full HD
    720: 50,    # HD
    576: 30,    # SD PAL
    480: 25,    # SD NTSC
}

# Ranking des codecs video
VIDEO_CODEC_SCORES = {
    'AV1': 100,
    'HEVC': 85,
    'H265': 85,
    'H.265': 85,
    'H264': 60,
    'H.264': 60,
    'VP9': 70,
    'MPEG4': 40,
    'XVID': 30,
    'DIVX': 30,
}

# Ranking des codecs audio
AUDIO_CODEC_SCORES = {
    'TrueHD': 100,
    'DTS-HD MA': 95,
    'DTS-HD': 90,
    'DTS:X': 90,
    'Atmos': 95,
    'FLAC': 85,
    'DTS': 70,
    'AC3': 60,
    'EAC3': 65,
    'AAC': 55,
    'MP3': 40,
}

# Score canaux audio
AUDIO_CHANNEL_SCORES = {
    '7.1': 100,
    '5.1': 75,
    '2.0': 50,
    '1.0': 25,
}


def score_resolution(resolution: Optional[Resolution]) -> float:
    """Score de resolution base sur la hauteur."""
    if not resolution:
        return 0.0

    height = resolution.height
    # Score exact si dans la table
    if height in RESOLUTION_SCORES:
        return RESOLUTION_SCORES[height]

    # Interpolation pour valeurs intermediaires
    for ref_height, ref_score in sorted(RESOLUTION_SCORES.items(), reverse=True):
        if height >= ref_height:
            return ref_score

    return 0.0


def score_video_codec(codec: Optional[VideoCodec]) -> float:
    """Score du codec video."""
    if not codec:
        return 0.0

    name = codec.name.upper()
    for codec_name, score in VIDEO_CODEC_SCORES.items():
        if codec_name in name:
            return score

    return 30.0  # Codec inconnu


def score_audio(codecs: tuple[AudioCodec, ...]) -> float:
    """Score audio combine (codec + canaux)."""
    if not codecs:
        return 0.0

    best_score = 0.0
    for codec in codecs:
        # Score codec
        codec_name = codec.name.upper()
        codec_score = 30.0  # Defaut
        for name, score in AUDIO_CODEC_SCORES.items():
            if name.upper() in codec_name:
                codec_score = score
                break

        # Score canaux
        channel_score = 50.0  # Defaut
        if codec.channels:
            for channels, score in AUDIO_CHANNEL_SCORES.items():
                if channels in codec.channels:
                    channel_score = score
                    break

        # Combine (70% codec, 30% canaux)
        combined = codec_score * 0.7 + channel_score * 0.3
        best_score = max(best_score, combined)

    return best_score


def calculate_quality_score(
    media_info: Optional[MediaInfo],
    file_size_bytes: int,
    duration_seconds: Optional[int] = None,
) -> QualityScore:
    """
    Calcule le score de qualite complet d'un fichier video.

    Poids:
    - Resolution: 30%
    - Codec video: 25%
    - Debit video: 20%
    - Audio: 15%
    - Efficacite taille: 10%
    """
    if not media_info:
        return QualityScore(
            resolution_score=0,
            video_codec_score=0,
            bitrate_score=0,
            audio_score=0,
            size_efficiency=50,  # Neutre
            total=0,
        )

    # Scores individuels
    res_score = score_resolution(media_info.resolution)
    codec_score = score_video_codec(media_info.video_codec)
    audio_score = score_audio(media_info.audio_codecs)

    # Debit video (normalise par resolution)
    bitrate_score = 50.0  # Defaut
    if duration_seconds and duration_seconds > 0:
        bitrate = (file_size_bytes * 8) / duration_seconds  # bits/sec
        # Normaliser par resolution attendue
        expected_bitrate = {
            2160: 25_000_000,  # 25 Mbps pour 4K
            1080: 8_000_000,   # 8 Mbps pour 1080p
            720: 4_000_000,    # 4 Mbps pour 720p
        }
        height = media_info.resolution.height if media_info.resolution else 1080
        expected = expected_bitrate.get(height, 8_000_000)
        ratio = min(bitrate / expected, 2.0)  # Plafonne a 200%
        bitrate_score = min(ratio * 50, 100)

    # Efficacite taille (plus petit = bonus, si qualite equivalente)
    # Score inversement proportionnel a la taille, normalise
    size_efficiency = 50.0  # Neutre par defaut
    if file_size_bytes > 0 and duration_seconds and duration_seconds > 0:
        # MB par minute
        mb_per_min = (file_size_bytes / 1024 / 1024) / (duration_seconds / 60)
        # Ideal: ~100 MB/h = 1.67 MB/min pour 1080p
        ideal = 1.67
        if mb_per_min < ideal:
            size_efficiency = min(100, 50 + (ideal - mb_per_min) * 20)
        else:
            size_efficiency = max(0, 50 - (mb_per_min - ideal) * 5)

    # Score total pondere
    total = (
        res_score * 0.30 +
        codec_score * 0.25 +
        bitrate_score * 0.20 +
        audio_score * 0.15 +
        size_efficiency * 0.10
    )

    return QualityScore(
        resolution_score=res_score,
        video_codec_score=codec_score,
        bitrate_score=bitrate_score,
        audio_score=audio_score,
        size_efficiency=size_efficiency,
        total=total,
    )
```

### Anti-Patterns to Avoid

- **shutil.move sans verification d'atomicite:** Peut echouer silencieusement sur cross-filesystem. Utiliser os.replace + staged copy.
- **Chemins absolus dans symlinks:** Casse la portabilite. Utiliser `relative_to(walk_up=True)`.
- **Sanitisation incomplete:** Ne pas oublier les ligatures francaises (oe, ae) qui ne sont pas normalisees par NFKC.
- **Subdivision statique:** A-D, E-H fixe. Utiliser subdivision dynamique basee sur le nombre reel de fichiers.
- **Rollback oublie:** Toujours implementer le chemin d'erreur pour restaurer l'etat initial.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Sanitisation nom fichier | Regex maison | pathvalidate | Edge cases Windows/Mac/Linux, caracteres reserves |
| Hash fichier video | SHA-256 complet | xxhash par echantillons | 10x plus rapide, existant dans hash_service.py |
| Extraction articles | Split manuel | IGNORED_ARTICLES constant | Liste complete fr/en/de/es deja dans constants.py |
| Atomicite move | shutil.move seul | os.replace + staged copy | shutil fallback non-atomique silencieusement |
| Chemin relatif symlink | Calcul manuel | pathlib.relative_to(walk_up=True) | Gere les .. automatiquement (Python 3.12+) |

**Key insight:** Les operations fichiers semblent simples mais ont de nombreux edge cases cross-platform. Utiliser les primitives Python verifiees et les abstractions existantes du projet.

## Common Pitfalls

### Pitfall 1: Perte de Donnees sur Cross-Filesystem Move

**What goes wrong:** shutil.move echoue au milieu d'une copie, fichier corrompu/perdu
**Why it happens:** Cross-filesystem move = copy + delete, non-atomique
**How to avoid:** Staged copy vers fichier temporaire sur destination, puis os.replace
**Warning signs:** Taille fichier differente apres move, extensions .tmp orphelines

### Pitfall 2: Symlinks Casses apres Renommage

**What goes wrong:** Symlinks existants pointent vers ancien chemin
**Why it happens:** Mise a jour du fichier reel sans mise a jour des symlinks
**How to avoid:** Toujours mettre a jour/recreer les symlinks apres renommage
**Warning signs:** Broken symlinks detectes par find_broken_links()

### Pitfall 3: Collision de Noms Non-Detectee

**What goes wrong:** Deux fichiers differents ecrases silencieusement
**Why it happens:** Verification par nom seul sans hash
**How to avoid:** Toujours comparer les hash avant remplacement
**Warning signs:** Nombre de fichiers qui diminue sans raison apparente

### Pitfall 4: Ligatures Non-Normalisees

**What goes wrong:** "Coeur" et "Coeur" (avec oe) crees comme fichiers differents
**Why it happens:** unicodedata.normalize() ne decompose pas oe/ae
**How to avoid:** Remplacement manuel des ligatures APRES normalisation NFKC
**Warning signs:** Doublons apparents dans la bibliotheque

### Pitfall 5: Subdivision Inconsistante

**What goes wrong:** Meme titre dans deux subdivisions differentes apres ajout de fichiers
**Why it happens:** Recalcul des plages qui change les bornes existantes
**How to avoid:** Determiner la subdivision cible au moment du classement, pas retroactivement
**Warning signs:** Fichiers "perdus" dans l'interface, structure incoherente

### Pitfall 6: Race Condition sur Symlink

**What goes wrong:** FileExistsError lors de la creation du symlink
**Why it happens:** Verification d'existence puis creation non-atomique
**How to avoid:** Supprimer le symlink existant juste avant creation, ou gerer l'exception
**Warning signs:** Echecs intermittents sur symlink creation

## Code Examples

Verified patterns from official sources:

### Chemin Relatif avec walk_up (Python 3.12+)

```python
# Source: https://docs.python.org/3/library/pathlib.html#pathlib.PurePath.relative_to
from pathlib import Path

storage = Path('/videos/storage/Films/Action/M/Matrix.mkv')
symlink_dir = Path('/videos/video/Films/Action/M')

# Calcul du chemin relatif pour le symlink
# walk_up=True permet d'ajouter des ..
relative = storage.relative_to(symlink_dir, walk_up=True)
# Resultat: PosixPath('../../storage/Films/Action/M/Matrix.mkv')
```

### Move Atomique Cross-Platform

```python
# Source: https://alexwlchan.net/2019/atomic-cross-filesystem-moves-in-python/
import os
import uuid
import shutil
from pathlib import Path

def atomic_move(source: Path, destination: Path) -> None:
    """Deplace un fichier de maniere atomique."""
    destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Tentative rename atomique (meme filesystem)
        os.replace(source, destination)
    except OSError:
        # Cross-filesystem: staged copy
        temp = destination.with_name(f".tmp_{uuid.uuid4().hex}")
        shutil.copy2(source, temp)
        os.replace(temp, destination)
        source.unlink()
```

### Sanitisation avec pathvalidate

```python
# Source: https://pathvalidate.readthedocs.io/en/latest/
from pathvalidate import sanitize_filename

# Cross-platform sanitization
clean = sanitize_filename("fi:l*e/p\"a?t>h|.txt", platform='universal')
# Resultat: "filepath.txt"

# Avec replacement text
clean = sanitize_filename("test:file.txt", replacement_text="-")
# Resultat: "test-file.txt"
```

### Creation Symlink Relatif

```python
# Source: https://docs.python.org/3/library/pathlib.html#pathlib.Path.symlink_to
from pathlib import Path

def create_relative_symlink(target: Path, link: Path) -> None:
    """Cree un symlink avec chemin relatif."""
    link.parent.mkdir(parents=True, exist_ok=True)

    # Supprimer si existe
    if link.is_symlink() or link.exists():
        link.unlink()

    # Calculer chemin relatif
    relative_target = target.relative_to(link.parent, walk_up=True)

    # Creer symlink
    link.symlink_to(relative_target)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| os.symlink + calcul manuel | pathlib.relative_to(walk_up=True) | Python 3.12 | Plus de calcul manuel de .. |
| shutil.move partout | os.replace + staged copy | Toujours | Atomicite garantie |
| MD5/SHA pour hash | xxhash3_64 | 2020+ | 10x plus rapide |
| regex pour sanitisation | pathvalidate | 2019+ | Cross-platform automatique |

**Deprecated/outdated:**
- `os.path` pour manipulation chemins : utiliser `pathlib`
- `shutil.move` sans verification : utiliser `os.replace` avec fallback

## Open Questions

Things that couldn't be fully resolved:

1. **Compatibilite Python 3.11 pour relative_to(walk_up=True)**
   - What we know: walk_up a ete ajoute en Python 3.12
   - What's unclear: Le projet cible Python 3.11+
   - Recommendation: Verifier la version minimum du projet. Si 3.11, implementer manuellement le calcul avec os.path.relpath()

2. **Comportement symlink sur Windows**
   - What we know: Windows necessite privileges admin ou Developer Mode
   - What's unclear: Le projet cible-t-il Windows?
   - Recommendation: Documenter les prerequis, ajouter detection au demarrage

3. **Gestion des fichiers tres longs (>255 caracteres)**
   - What we know: MAX_FILENAME_LENGTH = 200 devrait eviter le probleme
   - What's unclear: Comportement si le chemin complet depasse les limites
   - Recommendation: Ajouter verification du chemin complet, pas seulement du nom

## Sources

### Primary (HIGH confidence)
- [Python pathlib documentation](https://docs.python.org/3/library/pathlib.html) - symlink_to, relative_to, rename
- [pathvalidate documentation](https://pathvalidate.readthedocs.io/) - sanitize_filename API
- [xxhash PyPI](https://pypi.org/project/xxhash/) - hash_service.py existant dans le projet

### Secondary (MEDIUM confidence)
- [Python atomicwrites](https://python-atomicwrites.readthedocs.io/) - Patterns atomic move
- [alexwlchan atomic moves](https://alexwlchan.net/2019/atomic-cross-filesystem-moves-in-python/) - Cross-filesystem pattern

### Tertiary (LOW confidence)
- [Python unicodedata](https://docs.python.org/3/library/unicodedata.html) - normalize() ne decompose pas les ligatures

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Bibliotheques verifiees, certaines deja dans le projet
- Architecture: HIGH - Basee sur les ports/adapters existants du projet
- Pitfalls: MEDIUM - Bases sur documentation et patterns connus

**Research date:** 2026-01-27
**Valid until:** 2026-02-27 (30 days - operations fichiers stables)
