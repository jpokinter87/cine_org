"""
Implementation de l'extracteur de metadonnees techniques avec pymediainfo.

Ce module fournit MediaInfoExtractor qui implemente IMediaInfoExtractor
pour extraire resolution, codecs, langues et duree des fichiers video.
"""

from pathlib import Path
from typing import Optional

from pymediainfo import MediaInfo as PyMediaInfo

from src.core.ports.parser import IMediaInfoExtractor
from src.core.value_objects.media_info import (
    AudioCodec,
    Language,
    MediaInfo,
    Resolution,
    VideoCodec,
)


class MediaInfoExtractor(IMediaInfoExtractor):
    """
    Extracteur de metadonnees techniques utilisant pymediainfo.

    Extrait resolution, codecs video/audio, langues des pistes audio,
    et duree depuis les fichiers video.
    """

    # Mapping des codes de langue ISO 639-1 vers noms francais
    LANGUAGE_NAMES: dict[str, str] = {
        "fr": "Francais",
        "en": "Anglais",
        "de": "Allemand",
        "es": "Espagnol",
        "it": "Italien",
        "pt": "Portugais",
        "ja": "Japonais",
        "ko": "Coreen",
        "zh": "Chinois",
        "ru": "Russe",
        "ar": "Arabe",
        "nl": "Neerlandais",
        "pl": "Polonais",
        "sv": "Suedois",
        "da": "Danois",
        "no": "Norvegien",
        "fi": "Finnois",
        "cs": "Tcheque",
        "hu": "Hongrois",
        "tr": "Turc",
        "el": "Grec",
        "he": "Hebreu",
        "th": "Thai",
        "vi": "Vietnamien",
        "id": "Indonesien",
        "ms": "Malais",
        "hi": "Hindi",
    }

    # Mapping des codecs video vers noms normalises
    VIDEO_CODEC_MAPPING: dict[str, str] = {
        "avc": "x264",
        "h.264": "x264",
        "h264": "x264",
        "x264": "x264",
        "hevc": "x265",
        "h.265": "x265",
        "h265": "x265",
        "x265": "x265",
        "av1": "AV1",
        "vp9": "VP9",
        "mpeg-4 visual": "MPEG-4",
        "mpeg4": "MPEG-4",
        "xvid": "XviD",
        "divx": "DivX",
    }

    # Mapping des codecs audio vers noms normalises
    AUDIO_CODEC_MAPPING: dict[str, str] = {
        "aac": "AAC",
        "ac-3": "AC3",
        "ac3": "AC3",
        "e-ac-3": "E-AC3",
        "eac3": "E-AC3",
        "dts": "DTS",
        "dts-hd ma": "DTS-HD",
        "dts-hd": "DTS-HD",
        "dts-hd master audio": "DTS-HD",
        "truehd": "TrueHD",
        "mlp fba": "TrueHD",
        "flac": "FLAC",
        "pcm": "PCM",
        "opus": "Opus",
        "vorbis": "Vorbis",
        "mp3": "MP3",
        "mpeg audio": "MP3",
    }

    def extract(self, file_path: Path) -> Optional[MediaInfo]:
        """
        Extrait les metadonnees techniques d'un fichier video.

        Args:
            file_path: Chemin complet vers le fichier video

        Returns:
            MediaInfo avec les metadonnees extraites, ou None si
            l'extraction echoue (fichier non video, corrompu, etc.)
        """
        if not file_path.exists():
            return None

        try:
            media_info = PyMediaInfo.parse(str(file_path), full=True)
        except Exception:
            return None

        # Extraire les pistes video et audio
        video_tracks = [
            track for track in media_info.tracks if track.track_type == "Video"
        ]
        audio_tracks = [
            track for track in media_info.tracks if track.track_type == "Audio"
        ]
        general_tracks = [
            track for track in media_info.tracks if track.track_type == "General"
        ]

        # Extraire la resolution depuis la premiere piste video
        resolution = self._extract_resolution(video_tracks)

        # Extraire le codec video
        video_codec = self._extract_video_codec(video_tracks)

        # Extraire les codecs audio
        audio_codecs = self._extract_audio_codecs(audio_tracks)

        # Extraire les langues audio
        audio_languages = self._extract_audio_languages(audio_tracks)

        # Extraire la duree (en secondes, pas millisecondes!)
        duration_seconds = self._extract_duration(general_tracks)

        return MediaInfo(
            resolution=resolution,
            video_codec=video_codec,
            audio_codecs=audio_codecs,
            audio_languages=audio_languages,
            duration_seconds=duration_seconds,
        )

    def _extract_resolution(self, video_tracks: list) -> Optional[Resolution]:
        """
        Extrait la resolution depuis la premiere piste video.

        Args:
            video_tracks: Liste des pistes video

        Returns:
            Resolution ou None si pas de piste video
        """
        if not video_tracks:
            return None

        track = video_tracks[0]
        width = track.width
        height = track.height

        if width is None or height is None:
            return None

        return Resolution(width=int(width), height=int(height))

    def _extract_video_codec(self, video_tracks: list) -> Optional[VideoCodec]:
        """
        Extrait et normalise le codec video depuis la premiere piste video.

        Args:
            video_tracks: Liste des pistes video

        Returns:
            VideoCodec normalise ou None si pas de piste video
        """
        if not video_tracks:
            return None

        track = video_tracks[0]
        codec_name = track.format
        codec_profile = track.format_profile

        if codec_name is None:
            return None

        # Normaliser le nom du codec
        normalized_name = self._normalize_video_codec(codec_name)

        return VideoCodec(name=normalized_name, profile=codec_profile)

    def _normalize_video_codec(self, codec: str) -> str:
        """
        Normalise le nom du codec video.

        Args:
            codec: Nom du codec brut depuis mediainfo

        Returns:
            Nom normalise (x264, x265, AV1, etc.)
        """
        codec_lower = codec.lower()

        # Chercher dans le mapping
        for key, value in self.VIDEO_CODEC_MAPPING.items():
            if key in codec_lower:
                return value

        # Retourner le codec original si pas de mapping
        return codec

    def _extract_audio_codecs(self, audio_tracks: list) -> tuple[AudioCodec, ...]:
        """
        Extrait et normalise les codecs audio de toutes les pistes.

        Args:
            audio_tracks: Liste des pistes audio

        Returns:
            Tuple des AudioCodec extraits
        """
        codecs: list[AudioCodec] = []

        for track in audio_tracks:
            codec_name = track.format
            if codec_name is None:
                continue

            # Normaliser le nom du codec
            normalized_name = self._normalize_audio_codec(codec_name)

            # Extraire et formater les canaux
            channels = self._format_channels(track.channel_s)

            codecs.append(AudioCodec(name=normalized_name, channels=channels))

        return tuple(codecs)

    def _normalize_audio_codec(self, codec: str) -> str:
        """
        Normalise le nom du codec audio.

        Args:
            codec: Nom du codec brut depuis mediainfo

        Returns:
            Nom normalise (AAC, AC3, DTS-HD, etc.)
        """
        codec_lower = codec.lower()

        # Chercher dans le mapping
        for key, value in self.AUDIO_CODEC_MAPPING.items():
            if key in codec_lower:
                return value

        # Retourner le codec original si pas de mapping
        return codec

    def _format_channels(self, channel_count: Optional[int]) -> Optional[str]:
        """
        Formate le nombre de canaux audio en notation standard.

        Args:
            channel_count: Nombre de canaux (2, 6, 8, etc.)

        Returns:
            Notation standard (2.0, 5.1, 7.1, etc.) ou None
        """
        if channel_count is None:
            return None

        # Mapping nombre de canaux -> notation standard
        channel_mapping = {
            1: "1.0",
            2: "2.0",
            3: "2.1",
            6: "5.1",
            7: "6.1",
            8: "7.1",
        }

        return channel_mapping.get(channel_count, f"{channel_count}.0")

    def _extract_audio_languages(self, audio_tracks: list) -> tuple[Language, ...]:
        """
        Extrait les langues de toutes les pistes audio.

        Args:
            audio_tracks: Liste des pistes audio

        Returns:
            Tuple des Language extraites
        """
        languages: list[Language] = []
        seen_codes: set[str] = set()

        for track in audio_tracks:
            # pymediainfo peut fournir la langue en ISO 639-1 ou 639-2
            lang_code = track.language
            if lang_code is None:
                continue

            # Normaliser le code (prendre les 2 premiers caracteres pour ISO 639-1)
            code = lang_code.lower()[:2]

            # Eviter les doublons
            if code in seen_codes:
                continue
            seen_codes.add(code)

            # Obtenir le nom de la langue
            name = self._get_language_name(code)
            languages.append(Language(code=code, name=name))

        return tuple(languages)

    def _get_language_name(self, code: str) -> str:
        """
        Retourne le nom francais de la langue depuis son code ISO 639-1.

        Args:
            code: Code ISO 639-1 (fr, en, etc.)

        Returns:
            Nom francais de la langue
        """
        return self.LANGUAGE_NAMES.get(code, code.upper())

    def _extract_duration(self, general_tracks: list) -> Optional[int]:
        """
        Extrait la duree en SECONDES depuis la piste generale.

        CRITICAL: pymediainfo retourne la duree en millisecondes!
        On divise par 1000 pour obtenir des secondes.

        Args:
            general_tracks: Liste des pistes generales

        Returns:
            Duree en secondes ou None
        """
        if not general_tracks:
            return None

        track = general_tracks[0]
        duration_ms = track.duration

        if duration_ms is None:
            return None

        # IMPORTANT: Convertir millisecondes en secondes
        return int(float(duration_ms) / 1000)
