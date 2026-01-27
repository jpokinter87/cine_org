"""
Service d'évaluation de la qualité vidéo.

Ce module fournit les fonctions de scoring multi-critères pour
évaluer la qualité d'un fichier vidéo. Utilisé pour comparer
les doublons et recommander la meilleure version.

Critères évalués (poids):
- Résolution (30%): 4K > 1080p > 720p > SD
- Codec vidéo (25%): AV1 > HEVC > VP9 > H.264 > anciens
- Bitrate vidéo (20%): normalisé par résolution
- Audio (15%): codec + canaux (7.1 > 5.1 > stereo)
- Taille (10%): efficacité (qualité/taille)
"""

from dataclasses import dataclass
from typing import Optional

from src.core.value_objects.media_info import (
    MediaInfo,
    Resolution,
    VideoCodec,
    AudioCodec,
)


# ====================
# Poids des critères (doivent sommer à 100)
# ====================

WEIGHT_RESOLUTION = 30
WEIGHT_VIDEO_CODEC = 25
WEIGHT_BITRATE = 20
WEIGHT_AUDIO = 15
WEIGHT_SIZE = 10


# ====================
# Scores des codecs vidéo
# ====================

VIDEO_CODEC_SCORES: dict[str, float] = {
    # Moderne (meilleur)
    "av1": 100,
    # HEVC / H.265
    "hevc": 85,
    "h.265": 85,
    "h265": 85,
    "x265": 85,
    # VP9
    "vp9": 70,
    # H.264 / AVC
    "h.264": 60,
    "h264": 60,
    "avc": 60,
    "x264": 60,
    # VP8
    "vp8": 45,
    # Anciens
    "mpeg-4": 30,
    "mpeg4": 30,
    "xvid": 30,
    "divx": 30,
    "wmv": 25,
    "vc-1": 25,
}

DEFAULT_VIDEO_CODEC_SCORE = 30


# ====================
# Scores des codecs audio
# ====================

AUDIO_CODEC_SCORES: dict[str, float] = {
    # Lossless haut de gamme
    "truehd": 100,
    "dolby truehd": 100,
    "atmos": 100,
    "dts-hd ma": 95,
    "dts-hd": 90,
    "dts:x": 90,
    "pcm": 85,
    "flac": 85,
    # Lossy haute qualité
    "eac3": 75,
    "e-ac3": 75,
    "dolby digital plus": 75,
    "dts": 70,
    "ac3": 60,
    "dolby digital": 60,
    "aac": 55,
    # Lossy standard
    "mp3": 40,
    "wma": 35,
    "vorbis": 50,
    "opus": 65,
}

DEFAULT_AUDIO_CODEC_SCORE = 50


# ====================
# Scores des configurations de canaux
# ====================

CHANNEL_SCORES: dict[str, float] = {
    "7.1": 100,
    "8": 100,
    "7": 90,
    "6.1": 85,
    "5.1": 75,
    "6": 75,
    "5": 70,
    "5.0": 70,
    "4.1": 60,
    "4.0": 55,
    "4": 55,
    "3.1": 50,
    "3": 45,
    "2.1": 45,
    "2.0": 50,
    "stereo": 50,
    "2": 50,
    "1.0": 25,
    "mono": 25,
    "1": 25,
}

DEFAULT_CHANNEL_SCORE = 50


@dataclass(frozen=True)
class QualityScore:
    """
    Score de qualité d'un fichier vidéo.

    Contient les scores individuels par critère et le score total pondéré.

    Attributs :
        resolution_score: Score de résolution (0-100)
        video_codec_score: Score du codec vidéo (0-100)
        bitrate_score: Score du bitrate vidéo (0-100)
        audio_score: Score audio combiné (0-100)
        size_efficiency: Score d'efficacité taille (0-100)
        total: Score total pondéré (0-100)
    """

    resolution_score: float
    video_codec_score: float
    bitrate_score: float
    audio_score: float
    size_efficiency: float
    total: float

    @property
    def breakdown(self) -> dict[str, float]:
        """
        Retourne le détail des scores sous forme de dictionnaire.

        Utile pour l'affichage à l'utilisateur lors de comparaisons.
        """
        return {
            "resolution": self.resolution_score,
            "video_codec": self.video_codec_score,
            "bitrate": self.bitrate_score,
            "audio": self.audio_score,
            "size_efficiency": self.size_efficiency,
            "total": self.total,
        }


def score_resolution(resolution: Optional[Resolution]) -> float:
    """
    Calcule le score de résolution.

    Échelle :
    - 4K (>=2160p): 100
    - 1080p (>=1080p): 75
    - 720p (>=720p): 50
    - SD (<720p): 25
    - None: 0

    Args:
        resolution: Résolution du fichier vidéo.

    Returns:
        Score de 0 à 100.
    """
    if resolution is None:
        return 0

    height = resolution.height

    if height >= 2160:
        return 100
    elif height >= 1080:
        return 75
    elif height >= 720:
        return 50
    else:
        return 25


def score_video_codec(codec: Optional[VideoCodec]) -> float:
    """
    Calcule le score du codec vidéo.

    Échelle (de meilleur à pire) :
    - AV1: 100
    - HEVC/H.265: 85
    - VP9: 70
    - H.264/AVC: 60
    - VP8: 45
    - Anciens (MPEG-4, XVID, DivX): 30
    - Inconnu: 30

    Args:
        codec: Codec vidéo du fichier.

    Returns:
        Score de 0 à 100.
    """
    if codec is None:
        return 0

    codec_name = codec.name.lower()

    return VIDEO_CODEC_SCORES.get(codec_name, DEFAULT_VIDEO_CODEC_SCORE)


def _score_single_audio_codec(codec: AudioCodec) -> float:
    """
    Calcule le score d'un codec audio individuel.

    Combine le score du codec (70%) et des canaux (30%).

    Args:
        codec: Codec audio à évaluer.

    Returns:
        Score de 0 à 100.
    """
    codec_name = codec.name.lower()
    codec_score = AUDIO_CODEC_SCORES.get(codec_name, DEFAULT_AUDIO_CODEC_SCORE)

    if codec.channels:
        channels = codec.channels.lower()
        channel_score = CHANNEL_SCORES.get(channels, DEFAULT_CHANNEL_SCORE)
    else:
        channel_score = DEFAULT_CHANNEL_SCORE

    # Pondération: 70% codec, 30% canaux
    return codec_score * 0.7 + channel_score * 0.3


def score_audio(codecs: tuple[AudioCodec, ...]) -> float:
    """
    Calcule le score audio global.

    Si plusieurs pistes audio sont présentes, prend le meilleur score.
    Combine le score du codec (70%) et la configuration des canaux (30%).

    Échelle codecs (de meilleur à pire) :
    - TrueHD/Atmos: 100
    - DTS-HD MA: 95
    - DTS-HD: 90
    - PCM/FLAC: 85
    - EAC3/DTS: 70
    - AC3: 60
    - AAC: 55
    - MP3: 40

    Échelle canaux :
    - 7.1: 100
    - 5.1: 75
    - 2.0: 50
    - 1.0: 25

    Args:
        codecs: Tuple des codecs audio du fichier.

    Returns:
        Score de 0 à 100.
    """
    if not codecs:
        return 0

    # Calculer le score pour chaque piste et prendre le meilleur
    scores = [_score_single_audio_codec(codec) for codec in codecs]
    return max(scores)


def _calculate_bitrate_score(
    file_size_bytes: int,
    duration_seconds: Optional[int],
) -> float:
    """
    Calcule le score de bitrate.

    Le bitrate est normalisé. Un bitrate élevé indique généralement
    une meilleure qualité (moins de compression).

    Échelle approximative (pour 1080p) :
    - > 20 Mbps: 100
    - 10-20 Mbps: 85
    - 5-10 Mbps: 70
    - 2-5 Mbps: 55
    - < 2 Mbps: 40

    Args:
        file_size_bytes: Taille du fichier en octets.
        duration_seconds: Durée en secondes.

    Returns:
        Score de 0 à 100.
    """
    if not duration_seconds or duration_seconds <= 0:
        return 50  # Score neutre si durée inconnue

    # Calculer le bitrate en Mbps
    bitrate_bps = (file_size_bytes * 8) / duration_seconds
    bitrate_mbps = bitrate_bps / 1_000_000

    # Échelle de score
    if bitrate_mbps >= 20:
        return 100
    elif bitrate_mbps >= 15:
        return 90
    elif bitrate_mbps >= 10:
        return 80
    elif bitrate_mbps >= 5:
        return 65
    elif bitrate_mbps >= 2:
        return 50
    else:
        return 35


def _calculate_size_efficiency(
    file_size_bytes: int,
    resolution: Optional[Resolution],
    duration_seconds: Optional[int],
) -> float:
    """
    Calcule le score d'efficacité de taille.

    Un fichier plus petit pour une même qualité perçue est considéré
    comme plus efficace. Cependant, trop petit peut signifier une
    compression excessive.

    Args:
        file_size_bytes: Taille du fichier en octets.
        resolution: Résolution du fichier.
        duration_seconds: Durée en secondes.

    Returns:
        Score de 0 à 100.
    """
    if not duration_seconds or duration_seconds <= 0:
        return 50  # Score neutre

    # Taille attendue selon la résolution (en bytes par seconde)
    # Ces valeurs représentent une bonne qualité sans gaspillage
    expected_bps: dict[str, int] = {
        "4K": 3_000_000,      # ~24 Mbps
        "1080p": 1_500_000,   # ~12 Mbps
        "720p": 750_000,      # ~6 Mbps
        "SD": 375_000,        # ~3 Mbps
    }

    if resolution:
        label = resolution.label
        expected = expected_bps.get(label, 750_000)
    else:
        expected = 750_000  # Valeur par défaut

    expected_size = expected * duration_seconds
    actual_bps = file_size_bytes / duration_seconds

    # Ratio de la taille réelle vs attendue
    ratio = actual_bps / (expected / 1)  # Normaliser

    # Score: proche de 1 = bon, trop haut = gaspillage, trop bas = mauvaise qualité
    if 0.8 <= ratio <= 1.5:
        # Plage optimale
        return 85 + (1 - abs(ratio - 1)) * 15  # 85-100
    elif ratio > 1.5:
        # Fichier trop gros (mais pas forcément mauvais)
        return max(50, 85 - (ratio - 1.5) * 20)
    else:
        # Fichier trop petit (compression excessive probable)
        return max(30, ratio * 100)


def calculate_quality_score(
    media_info: Optional[MediaInfo],
    file_size_bytes: int,
    duration_seconds: Optional[int] = None,
) -> QualityScore:
    """
    Calcule le score de qualité global d'un fichier vidéo.

    Combine plusieurs critères avec des poids définis :
    - Résolution: 30%
    - Codec vidéo: 25%
    - Bitrate: 20%
    - Audio: 15%
    - Efficacité taille: 10%

    Args:
        media_info: Informations techniques du fichier.
        file_size_bytes: Taille du fichier en octets.
        duration_seconds: Durée en secondes (optionnel, utilise media_info si absent).

    Returns:
        QualityScore avec les scores détaillés et le total.
    """
    if media_info is None:
        return QualityScore(
            resolution_score=0,
            video_codec_score=0,
            bitrate_score=0,
            audio_score=0,
            size_efficiency=0,
            total=0,
        )

    # Utiliser la durée de media_info si non fournie
    duration = duration_seconds or media_info.duration_seconds

    # Calculer les scores individuels
    resolution_score = score_resolution(media_info.resolution)
    video_codec_score = score_video_codec(media_info.video_codec)
    audio_score_val = score_audio(media_info.audio_codecs)
    bitrate_score = _calculate_bitrate_score(file_size_bytes, duration)
    size_efficiency = _calculate_size_efficiency(
        file_size_bytes, media_info.resolution, duration
    )

    # Calculer le score total pondéré
    total = (
        resolution_score * WEIGHT_RESOLUTION
        + video_codec_score * WEIGHT_VIDEO_CODEC
        + bitrate_score * WEIGHT_BITRATE
        + audio_score_val * WEIGHT_AUDIO
        + size_efficiency * WEIGHT_SIZE
    ) / 100

    return QualityScore(
        resolution_score=resolution_score,
        video_codec_score=video_codec_score,
        bitrate_score=bitrate_score,
        audio_score=audio_score_val,
        size_efficiency=size_efficiency,
        total=total,
    )


class QualityScorerService:
    """
    Service d'évaluation de la qualité vidéo.

    Fournit les méthodes de haut niveau pour évaluer et comparer
    la qualité des fichiers vidéo.

    Ce service est sans état et peut être utilisé comme singleton.
    """

    def calculate_quality_score(
        self,
        media_info: Optional[MediaInfo],
        file_size_bytes: int,
        duration_seconds: Optional[int] = None,
    ) -> QualityScore:
        """
        Calcule le score de qualité d'un fichier.

        Voir calculate_quality_score() pour les détails.
        """
        return calculate_quality_score(media_info, file_size_bytes, duration_seconds)

    def score_resolution(self, resolution: Optional[Resolution]) -> float:
        """
        Calcule le score de résolution.

        Voir score_resolution() pour les détails.
        """
        return score_resolution(resolution)

    def score_video_codec(self, codec: Optional[VideoCodec]) -> float:
        """
        Calcule le score du codec vidéo.

        Voir score_video_codec() pour les détails.
        """
        return score_video_codec(codec)

    def score_audio(self, codecs: tuple[AudioCodec, ...]) -> float:
        """
        Calcule le score audio.

        Voir score_audio() pour les détails.
        """
        return score_audio(codecs)
