"""
Service de détection de doublons pré-transfert.

Détecte si un titre similaire existe déjà dans les répertoires symlinks
avant le transfert. Calcule et compare les scores de qualité pour
recommander la meilleure version.

Utilise les structures existantes de TransfererService (ExistingFileInfo,
SimilarContentInfo) et QualityScorerService.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.services.quality_scorer import (
    AUDIO_CODEC_SCORES,
    DEFAULT_AUDIO_CODEC_SCORE,
    DEFAULT_VIDEO_CODEC_SCORE,
    VIDEO_CODEC_SCORES,
)
from src.services.transferer import ExistingFileInfo
from src.utils.constants import VIDEO_EXTENSIONS


@dataclass
class QualityComparison:
    """Résultat de la comparaison de qualité entre deux versions."""

    existing_score: float
    new_score: float
    recommended: str  # "new" ou "old"
    existing_breakdown: dict[str, str] = field(default_factory=dict)
    new_breakdown: dict[str, str] = field(default_factory=dict)


@dataclass
class DuplicateMatch:
    """Résultat de la détection d'un doublon pré-transfert."""

    existing_dir: Path
    existing_title: str
    existing_files: list[ExistingFileInfo]
    similarity_reason: str
    quality: Optional[QualityComparison] = None
    existing_seasons: Optional[set[int]] = None


# Articles ignorés pour la normalisation des titres
_ARTICLES = {"le", "la", "les", "l", "the", "a", "an", "un", "une", "des"}


def _normalize_title(title: str) -> str:
    """Normalise un titre pour comparaison (minuscules, sans articles, sans ponctuation)."""
    import unicodedata

    # Décomposer les accents
    normalized = unicodedata.normalize("NFD", title.lower())
    # Retirer les diacritiques
    normalized = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
    # Retirer la ponctuation
    normalized = re.sub(r"[^\w\s]", "", normalized)
    # Retirer les articles en début
    words = normalized.split()
    if words and words[0] in _ARTICLES:
        words = words[1:]
    return " ".join(words).strip()


def _extract_title_year(name: str) -> tuple[str, Optional[int]]:
    """Extrait le titre et l'année d'un nom de dossier."""
    match = re.match(r"^(.+?)\s*\((\d{4})\)$", name)
    if match:
        return match.group(1).strip(), int(match.group(2))
    return name, None


def _score_file_info(info: ExistingFileInfo) -> float:
    """
    Calcule un score de qualité simplifié depuis ExistingFileInfo.

    Utilise les mêmes tables de scoring que QualityScorerService
    mais travaille avec les strings de ExistingFileInfo au lieu
    de MediaInfo.
    """
    score = 0.0

    # Résolution (25%)
    res_map = {"4K": 100, "2160p": 100, "1080p": 75, "720p": 50, "SD": 25}
    res_label = info.resolution or ""
    res_score = res_map.get(res_label, 0)
    # Essayer aussi la hauteur brute (ex: "1920x1080")
    if not res_score and "x" in res_label:
        try:
            height = int(res_label.split("x")[1])
            if height >= 2160:
                res_score = 100
            elif height >= 1080:
                res_score = 75
            elif height >= 720:
                res_score = 50
            else:
                res_score = 25
        except (ValueError, IndexError):
            pass
    score += res_score * 0.25

    # Codec vidéo (20%)
    vc = (info.video_codec or "").lower()
    vc_score = VIDEO_CODEC_SCORES.get(vc, DEFAULT_VIDEO_CODEC_SCORE) if vc else 0
    score += vc_score * 0.20

    # Codec audio (15%)
    ac = (info.audio_codec or "").lower()
    ac_score = AUDIO_CODEC_SCORES.get(ac, DEFAULT_AUDIO_CODEC_SCORE) if ac else 0
    score += ac_score * 0.15

    # Bitrate vidéo (25%) — normalisé par l'efficacité du codec
    # Les codecs modernes (AV1, HEVC) offrent la même qualité à bitrate inférieur.
    # On normalise vers un équivalent x264 pour comparer équitablement.
    _CODEC_EFFICIENCY: dict[str, float] = {
        "av1": 3.0,  # AV1 ≈ même qualité que x264 à ~33% du bitrate
        "hevc": 2.0,
        "h.265": 2.0,
        "h265": 2.0,
        "x265": 2.0,
        "vp9": 1.8,
        "h.264": 1.0,  # Référence
        "h264": 1.0,
        "avc": 1.0,
        "x264": 1.0,
        "vp8": 0.9,
        "mpeg-4": 0.8,
        "mpeg4": 0.8,
        "xvid": 0.8,
        "divx": 0.8,
    }

    v_bitrate_kbps = None
    if info.video_bitrate_kbps:
        v_bitrate_kbps = float(info.video_bitrate_kbps)
    elif info.duration_seconds and info.duration_seconds > 0 and info.size_bytes:
        # Fallback : débit global (inclut audio + overhead, ~20% de plus)
        v_bitrate_kbps = (info.size_bytes * 8) / info.duration_seconds / 1000

    if v_bitrate_kbps is not None:
        # Normaliser le bitrate par l'efficacité du codec
        efficiency = _CODEC_EFFICIENCY.get(vc, 1.0) if vc else 1.0
        effective_kbps = v_bitrate_kbps * efficiency

        if effective_kbps >= 5_000:
            v_bitrate_score = 100
        elif effective_kbps >= 3_000:
            v_bitrate_score = 90
        elif effective_kbps >= 2_000:
            v_bitrate_score = 80
        elif effective_kbps >= 1_500:
            v_bitrate_score = 65
        elif effective_kbps >= 1_000:
            v_bitrate_score = 50
        elif effective_kbps >= 500:
            v_bitrate_score = 35
        else:
            v_bitrate_score = 20
    else:
        # Fallback sur la taille brute comme proxy
        size_gb = info.size_bytes / (1024**3) if info.size_bytes else 0
        if size_gb >= 10:
            v_bitrate_score = 100
        elif size_gb >= 5:
            v_bitrate_score = 80
        elif size_gb >= 2:
            v_bitrate_score = 65
        elif size_gb >= 1:
            v_bitrate_score = 50
        elif size_gb >= 0.5:
            v_bitrate_score = 35
        else:
            v_bitrate_score = 20
    score += v_bitrate_score * 0.25

    # Bitrate audio (15%) — débit audio réel si disponible
    # Échelle : 64-640 Kb/s typique pour fichiers compressés
    a_bitrate_score = 0
    if info.audio_bitrate_kbps:
        a_kbps = info.audio_bitrate_kbps
        if a_kbps >= 640:
            a_bitrate_score = 100
        elif a_kbps >= 448:
            a_bitrate_score = 90
        elif a_kbps >= 320:
            a_bitrate_score = 80
        elif a_kbps >= 192:
            a_bitrate_score = 65
        elif a_kbps >= 128:
            a_bitrate_score = 50
        elif a_kbps >= 64:
            a_bitrate_score = 35
        else:
            a_bitrate_score = 20
    score += a_bitrate_score * 0.15

    return score


_RESOLUTION_PATTERNS = re.compile(r"\b(4K|2160p|1080p|720p|480p|SD)\b", re.IGNORECASE)
_VIDEO_CODEC_PATTERNS = re.compile(
    r"\b(AV1|HEVC|H\.?265|x265|VP9|H\.?264|x264|AVC|MPEG-?4|DivX|XviD)\b",
    re.IGNORECASE,
)
_AUDIO_CODEC_PATTERNS = re.compile(
    r"\b(TrueHD|Atmos|DTS-HD(?:\s*MA)?|DTS:X|DTS|EAC3|E-AC3|AC3|FLAC|AAC|MP3|PCM|Opus|Vorbis)\b",
    re.IGNORECASE,
)


def _extract_metadata_from_filename(
    filename: str,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Extrait résolution, codec vidéo et codec audio depuis un nom de fichier standardisé."""
    resolution = None
    video_codec = None
    audio_codec = None

    m = _RESOLUTION_PATTERNS.search(filename)
    if m:
        resolution = m.group(1)

    m = _VIDEO_CODEC_PATTERNS.search(filename)
    if m:
        video_codec = m.group(1)

    m = _AUDIO_CODEC_PATTERNS.search(filename)
    if m:
        audio_codec = m.group(1)

    return resolution, video_codec, audio_codec


class DuplicateDetector:
    """
    Détecte les doublons pré-transfert dans les répertoires symlinks.

    Scanne les répertoires video/ (Films/ et Series/) pour trouver
    des titres similaires avant le transfert. Calcule les scores de
    qualité pour recommander la meilleure version.
    """

    def detect_duplicate(
        self,
        title: str,
        year: Optional[int],
        video_dir: Path,
        is_series: bool = False,
    ) -> Optional[DuplicateMatch]:
        """
        Détecte si un titre similaire existe déjà dans video_dir.

        Pour les films : cherche dans video_dir/Films/ récursivement.
        Pour les séries : cherche dans video_dir/Series/ récursivement.

        Args:
            title: Titre du nouveau contenu.
            year: Année du nouveau contenu.
            video_dir: Répertoire racine des symlinks.
            is_series: True pour les séries.

        Returns:
            DuplicateMatch si un doublon est trouvé, None sinon.
        """
        if is_series:
            root = video_dir / "Series"
        else:
            root = video_dir / "Films"

        if not root.exists():
            return None

        normalized_new = _normalize_title(title)
        new_name = f"{title} ({year})" if year else title

        return self._scan_directory_recursive(
            root, normalized_new, new_name, title, year, is_series
        )

    def _scan_directory_recursive(
        self,
        directory: Path,
        normalized_new: str,
        new_name: str,
        title: str,
        year: Optional[int],
        is_series: bool,
    ) -> Optional[DuplicateMatch]:
        """Scanne récursivement les sous-répertoires à la recherche d'un titre similaire."""
        try:
            entries = list(directory.iterdir())
        except PermissionError:
            return None

        for subdir in entries:
            if not subdir.is_dir():
                continue

            dir_name = subdir.name
            existing_title, existing_year = _extract_title_year(dir_name)
            normalized_existing = _normalize_title(existing_title)

            if normalized_new == normalized_existing:
                # Titre similaire trouvé — vérifier qu'il y a des fichiers
                files_info = self._collect_files_info(subdir, is_series)

                if not files_info and not is_series:
                    # Dossier vide pour un film — pas un vrai doublon
                    continue

                # Déterminer la raison
                if dir_name == new_name:
                    if not files_info:
                        continue
                    reason = "Contenu existant avec le même nom"
                elif existing_year is None and year is not None:
                    reason = f"L'existant n'a pas d'année, le nouveau a ({year})"
                elif existing_year is not None and year is None:
                    reason = (
                        f"L'existant a une année ({existing_year}), "
                        f"le nouveau n'en a pas"
                    )
                elif existing_year != year:
                    reason = (
                        f"Années différentes : existant ({existing_year}) "
                        f"vs nouveau ({year})"
                    )
                else:
                    reason = f"Noms différents : '{dir_name}' vs '{new_name}'"

                # Collecter les numéros de saison pour les séries
                existing_seasons = None
                if is_series:
                    existing_seasons = self._collect_existing_seasons(subdir)

                return DuplicateMatch(
                    existing_dir=subdir,
                    existing_title=existing_title,
                    existing_files=files_info,
                    similarity_reason=reason,
                    existing_seasons=existing_seasons,
                )

            # Descendre dans les sous-répertoires de subdivision (lettres, plages)
            # Les dossiers de séries (avec Saison) ou de films (avec fichiers vidéo)
            # ne sont PAS des subdivisions
            if self._is_subdivision_dir(subdir):
                result = self._scan_directory_recursive(
                    subdir, normalized_new, new_name, title, year, is_series
                )
                if result:
                    return result

        return None

    def _is_subdivision_dir(self, directory: Path) -> bool:
        """
        Vérifie si un répertoire est une subdivision alphabétique.

        Les subdivisions contiennent d'autres dossiers mais pas directement
        de fichiers vidéo ni de dossiers 'Saison'.
        """
        name = directory.name
        # Patterns de subdivision : lettres (A-B, Ga-Ha), types (TV, Animation)
        # On ne descend PAS dans les dossiers qui sont clairement du contenu
        if name.startswith("Saison"):
            return False

        has_video_files = False
        has_subdirs = False
        has_season_dirs = False

        try:
            for item in directory.iterdir():
                if item.is_dir():
                    has_subdirs = True
                    if item.name.startswith("Saison"):
                        has_season_dirs = True
                elif item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS:
                    has_video_files = True
                    break  # Optimisation : un fichier vidéo suffit
        except PermissionError:
            return False

        # Un dossier avec des fichiers vidéo n'est pas une subdivision
        if has_video_files:
            return False

        # Un dossier contenant des sous-dossiers "Saison" est un dossier de série, pas une subdivision
        if has_season_dirs:
            return False

        # Un dossier avec des sous-dossiers est potentiellement une subdivision
        return has_subdirs

    @staticmethod
    def _collect_existing_seasons(series_dir: Path) -> set[int]:
        """Collecte les numéros de saison présents dans un dossier de série."""
        seasons = set()
        try:
            for item in series_dir.iterdir():
                if item.is_dir():
                    m = re.match(r"Saison\s+(\d+)", item.name)
                    if m:
                        seasons.add(int(m.group(1)))
        except PermissionError:
            pass
        return seasons

    def _collect_files_info(
        self, directory: Path, is_series: bool
    ) -> list[ExistingFileInfo]:
        """Collecte les fichiers vidéo dans un répertoire (récursivement pour les séries).

        Extrait les métadonnées techniques (résolution, codecs) depuis le nom
        de fichier standardisé. Extrait la durée via mediainfo sur le premier
        fichier uniquement (pour le calcul du bitrate).
        """
        files_info = []
        first_mi: Optional[DuplicateDetector._MediaInfoResult] = None

        if is_series:
            pattern = directory.rglob("*")
        else:
            pattern = directory.iterdir()

        for item in pattern:
            if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS:
                try:
                    size = item.stat().st_size
                except OSError:
                    size = 0
                resolution, video_codec, audio_codec = _extract_metadata_from_filename(
                    item.name
                )

                # Extraire métadonnées mediainfo sur le premier fichier seulement
                if first_mi is None:
                    first_mi = self._extract_mediainfo(item)

                # Combler les trous avec mediainfo (nom de fichier prioritaire)
                if not video_codec and first_mi.video_codec:
                    video_codec = first_mi.video_codec
                if not audio_codec and first_mi.audio_codec:
                    audio_codec = first_mi.audio_codec

                files_info.append(
                    ExistingFileInfo(
                        path=item,
                        size_bytes=size,
                        resolution=resolution,
                        video_codec=video_codec,
                        audio_codec=audio_codec,
                        duration_seconds=first_mi.duration,
                        video_bitrate_kbps=first_mi.video_bitrate_kbps,
                        audio_bitrate_kbps=first_mi.audio_bitrate_kbps,
                    )
                )

        return files_info

    @dataclass
    class _MediaInfoResult:
        """Résultat de l'extraction mediainfo."""

        duration: Optional[int] = None
        video_bitrate_kbps: Optional[int] = None
        audio_bitrate_kbps: Optional[int] = None
        video_codec: Optional[str] = None
        audio_codec: Optional[str] = None

    @staticmethod
    def _extract_mediainfo(file_path: Path) -> "_MediaInfoResult":
        """Extrait durée, débits et codecs d'un fichier via mediainfo.

        Les codecs sont extraits en complément du nom de fichier
        (fallback quand le nom standardisé ne contient pas l'info).
        """
        result = DuplicateDetector._MediaInfoResult()
        try:
            from pymediainfo import MediaInfo as PyMediaInfo

            parsed = PyMediaInfo.parse(str(file_path))

            for track in parsed.tracks:
                if track.track_type == "General" and result.duration is None:
                    if track.duration is not None:
                        result.duration = int(float(track.duration) / 1000)
                elif track.track_type == "Video":
                    if result.video_bitrate_kbps is None and track.bit_rate is not None:
                        result.video_bitrate_kbps = int(float(track.bit_rate) / 1000)
                    if result.video_codec is None and track.codec_id:
                        # Normaliser : V_MPEGH/ISO/HEVC → HEVC, etc.
                        cid = track.codec_id
                        if "HEVC" in cid or "265" in cid:
                            result.video_codec = "HEVC"
                        elif "AVC" in cid or "264" in cid:
                            result.video_codec = "H.264"
                        elif "AV1" in cid.upper():
                            result.video_codec = "AV1"
                        elif "VP9" in cid.upper():
                            result.video_codec = "VP9"
                        elif track.format:
                            result.video_codec = track.format
                elif track.track_type == "Audio":
                    if result.audio_bitrate_kbps is None and track.bit_rate is not None:
                        result.audio_bitrate_kbps = int(float(track.bit_rate) / 1000)
                    if result.audio_codec is None:
                        # Utiliser commercial_name ou format
                        fmt = (track.commercial_name or track.format or "").strip()
                        if fmt:
                            result.audio_codec = fmt
        except Exception:
            pass
        return result

    def compare_quality(
        self,
        existing_files: list[ExistingFileInfo],
        new_file: ExistingFileInfo,
    ) -> QualityComparison:
        """
        Compare la qualité entre les fichiers existants et le nouveau.

        Args:
            existing_files: Fichiers existants avec métadonnées.
            new_file: Nouveau fichier avec métadonnées.

        Returns:
            QualityComparison avec scores et recommandation.
        """
        # Score du nouveau
        new_score = _score_file_info(new_file)

        # Score existant = meilleur score parmi les fichiers
        existing_score = 0.0
        if existing_files:
            existing_score = max(_score_file_info(f) for f in existing_files)

        # À qualité égale ou meilleure, recommander le nouveau
        recommended = "new" if new_score >= existing_score else "old"

        # Breakdown pour affichage
        def _breakdown(info: ExistingFileInfo) -> dict[str, str]:
            # Débit vidéo
            v_bitrate_str = "?"
            if info.video_bitrate_kbps:
                kbps = info.video_bitrate_kbps
                if kbps >= 1000:
                    v_bitrate_str = f"{kbps / 1000:.1f} Mb/s"
                else:
                    v_bitrate_str = f"{kbps} Kb/s"
            elif (
                info.duration_seconds and info.duration_seconds > 0 and info.size_bytes
            ):
                # Fallback : estimation depuis taille globale
                kbps = (info.size_bytes * 8) / info.duration_seconds / 1000
                if kbps >= 1000:
                    v_bitrate_str = f"~{kbps / 1000:.1f} Mb/s"
                else:
                    v_bitrate_str = f"~{kbps:.0f} Kb/s"
            # Débit audio
            a_bitrate_str = "?"
            if info.audio_bitrate_kbps:
                a_bitrate_str = f"{info.audio_bitrate_kbps} Kb/s"
            return {
                "resolution": info.resolution or "?",
                "video_codec": info.video_codec or "?",
                "audio_codec": info.audio_codec or "?",
                "video_bitrate": v_bitrate_str,
                "audio_bitrate": a_bitrate_str,
                "size": _format_size(info.size_bytes),
            }

        best_existing = (
            max(existing_files, key=_score_file_info) if existing_files else None
        )

        return QualityComparison(
            existing_score=round(existing_score, 1),
            new_score=round(new_score, 1),
            recommended=recommended,
            existing_breakdown=_breakdown(best_existing) if best_existing else {},
            new_breakdown=_breakdown(new_file),
        )


def _format_size(size_bytes: int) -> str:
    """Formate une taille en octets en chaîne lisible."""
    if size_bytes >= 1_073_741_824:
        return f"{size_bytes / 1_073_741_824:.1f} Go"
    if size_bytes >= 1_048_576:
        return f"{size_bytes / 1_048_576:.0f} Mo"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.0f} Ko"
    return f"{size_bytes} o"
