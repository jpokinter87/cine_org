"""
Implementation du parser de noms de fichiers avec guessit.

Ce module fournit GuessitFilenameParser qui implemente IFilenameParser
pour extraire les informations structurees des noms de fichiers video.
"""

import re
from typing import Any, Optional

from guessit import guessit

from src.core.ports.parser import IFilenameParser
from src.core.value_objects.parsed_info import MediaType, ParsedFilename


class GuessitFilenameParser(IFilenameParser):
    """
    Parser de noms de fichiers utilisant la bibliotheque guessit.

    Extrait titre, annee, saison, episode, codecs, resolution, etc.
    depuis un nom de fichier video.
    """

    # Fallback regex pour les mots-clés FR "épisode/ép" que guessit ignore.
    # Capture les variantes avec/sans accent, point, virgule séparateur. Word
    # boundary à droite pour éviter de capturer "épisode2" sans espace (peu
    # probable mais on reste strict).
    _FR_EPISODE_RE = re.compile(
        r"\b(?:é|e)p(?:isode)?\.?\s*(\d{1,3})\b",
        re.IGNORECASE,
    )
    # Idem pour "saison N" — guessit la reconnaît déjà mais on garde le
    # fallback par symétrie (utile si un filename atypique la masque).
    _FR_SEASON_RE = re.compile(r"\bsaison\s*(\d{1,2})\b", re.IGNORECASE)

    def parse(
        self, filename: str, type_hint: Optional[MediaType] = None
    ) -> ParsedFilename:
        """
        Parse un nom de fichier video et extrait les informations structurees.

        Args:
            filename: Nom du fichier a parser (sans le chemin)
            type_hint: Indication du type de media attendu (depuis le repertoire source).
                       Si fourni, force guessit a utiliser ce type.

        Returns:
            ParsedFilename avec les informations extraites.
        """
        # Construire les options pour guessit
        options = self._build_options(type_hint)

        # Appeler guessit
        result = guessit(filename, options)

        # Fallback FR : guessit n'identifie pas "épisode N" (avec accent) ni
        # "Ép N" abrégé — fréquent sur les rips français. Si guessit n'a pas
        # trouvé d'épisode, on tente la regex sur le filename brut.
        if "episode" not in result:
            match = self._FR_EPISODE_RE.search(filename)
            if match:
                result["episode"] = int(match.group(1))
        if "season" not in result:
            match = self._FR_SEASON_RE.search(filename)
            if match:
                result["season"] = int(match.group(1))

        # Mapper vers ParsedFilename
        return self._map_to_parsed_filename(result, type_hint)

    def _build_options(self, type_hint: Optional[MediaType]) -> dict[str, Any]:
        """
        Construit le dictionnaire d'options pour guessit.

        Args:
            type_hint: Type de media attendu

        Returns:
            Dictionnaire d'options pour guessit
        """
        options: dict[str, Any] = {}

        if type_hint is not None:
            if type_hint == MediaType.MOVIE:
                options["type"] = "movie"
            elif type_hint == MediaType.SERIES:
                options["type"] = "episode"
            # UNKNOWN: ne pas forcer le type, laisser guessit deviner

        return options

    def _map_to_parsed_filename(
        self, result: dict[str, Any], type_hint: Optional[MediaType]
    ) -> ParsedFilename:
        """
        Mappe le resultat guessit vers un ParsedFilename.

        Args:
            result: Dictionnaire retourne par guessit
            type_hint: Type de media attendu (pour override si fourni)

        Returns:
            ParsedFilename avec les informations mappees
        """
        # Extraire le titre
        title = self._extract_title(result)

        # Determiner le type de media
        if type_hint is not None and type_hint != MediaType.UNKNOWN:
            media_type = type_hint
        else:
            media_type = self._map_type(result.get("type"))

        # Extraire l'annee
        year = result.get("year")

        # Extraire saison/episode pour les series
        season_raw = result.get("season")
        season = season_raw[0] if isinstance(season_raw, list) else season_raw
        episode = self._get_episode_start(result)
        episode_end = self._get_episode_end(result)
        episode_title = result.get("episode_title")

        # Extraire les infos techniques
        video_codec = self._extract_video_codec(result)
        audio_codec = self._extract_audio_codec(result)
        resolution = self._extract_resolution(result)
        source = self._extract_source(result)
        release_group = result.get("release_group")
        language = self._extract_language(result)

        subtitle_language = self._extract_subtitle_language(result)

        # Extraire le numero de partie (films decoupes par le rippeur)
        part, title = self._extract_part(result, title)

        return ParsedFilename(
            title=title,
            year=year,
            media_type=media_type,
            season=season,
            episode=episode,
            episode_end=episode_end,
            episode_title=episode_title,
            video_codec=video_codec,
            audio_codec=audio_codec,
            resolution=resolution,
            source=source,
            release_group=release_group,
            language=language,
            subtitle_language=subtitle_language,
            part=part,
        )

    def _extract_title(self, result: dict[str, Any]) -> str:
        """
        Extrait le titre depuis le resultat guessit.

        Args:
            result: Dictionnaire retourne par guessit

        Returns:
            Titre extrait, ou le nom de fichier sans extension en fallback
        """
        title = result.get("title")
        if title:
            return str(title)
        # Fallback: utiliser le nom sans extension si pas de titre
        return result.get("alternative_title", "Unknown")

    def _map_type(self, guessit_type: Optional[str]) -> MediaType:
        """
        Mappe le type guessit vers MediaType.

        Args:
            guessit_type: Type retourne par guessit ("movie", "episode", etc.)

        Returns:
            MediaType correspondant
        """
        if guessit_type == "movie":
            return MediaType.MOVIE
        elif guessit_type == "episode":
            return MediaType.SERIES
        else:
            return MediaType.UNKNOWN

    def _get_episode_start(self, result: dict[str, Any]) -> Optional[int]:
        """
        Extrait le premier numero d'episode.

        Args:
            result: Dictionnaire retourne par guessit

        Returns:
            Numero d'episode de debut, ou None
        """
        episode = result.get("episode")
        if episode is None:
            return None
        if isinstance(episode, list):
            return episode[0]
        return episode

    def _get_episode_end(self, result: dict[str, Any]) -> Optional[int]:
        """
        Extrait le dernier numero d'episode pour les doubles episodes.

        Args:
            result: Dictionnaire retourne par guessit

        Returns:
            Numero d'episode de fin si multi-episode, sinon None
        """
        episode = result.get("episode")
        if episode is None:
            return None
        if isinstance(episode, list) and len(episode) > 1:
            return episode[-1]
        return None

    def _extract_video_codec(self, result: dict[str, Any]) -> Optional[str]:
        """
        Extrait le codec video depuis le resultat guessit.

        Args:
            result: Dictionnaire retourne par guessit

        Returns:
            Codec video normalise, ou None
        """
        codec = result.get("video_codec")
        if codec is None:
            return None
        return str(codec)

    def _extract_audio_codec(self, result: dict[str, Any]) -> Optional[str]:
        """
        Extrait le codec audio depuis le resultat guessit.

        Args:
            result: Dictionnaire retourne par guessit

        Returns:
            Codec audio, ou None
        """
        codec = result.get("audio_codec")
        if codec is None:
            return None
        return str(codec)

    def _extract_resolution(self, result: dict[str, Any]) -> Optional[str]:
        """
        Extrait la resolution depuis le resultat guessit.

        Args:
            result: Dictionnaire retourne par guessit

        Returns:
            Resolution (ex: "1080p"), ou None
        """
        screen_size = result.get("screen_size")
        if screen_size is None:
            return None
        return str(screen_size)

    def _extract_source(self, result: dict[str, Any]) -> Optional[str]:
        """
        Extrait la source depuis le resultat guessit.

        Args:
            result: Dictionnaire retourne par guessit

        Returns:
            Source (ex: "Blu-ray", "HDTV"), ou None
        """
        source = result.get("source")
        if source is None:
            return None
        return str(source)

    def _extract_language(self, result: dict[str, Any]) -> Optional[str]:
        """
        Extrait la langue principale depuis le resultat guessit.

        Guessit retourne un objet Language de Babelfish.
        On extrait le code alpha2 en majuscules.
        Cas special : "mul" (multiple) est normalise en "Multi".

        Args:
            result: Dictionnaire retourne par guessit

        Returns:
            Code langue en majuscules (ex: "FR", "EN", "Multi"), ou None
        """
        language = result.get("language")
        if language is None:
            return None

        # guessit peut retourner une liste de langues ou une seule langue
        if isinstance(language, list):
            if len(language) == 0:
                return None
            language = language[0]

        # Babelfish Language object a un attribut alpha2
        try:
            code = language.alpha2
        except AttributeError:
            code = str(language)

        # Normaliser "mul" (multiple languages) en "Multi"
        if code.lower() == "mul":
            return "Multi"

        return code.upper()

    # Mapping chiffres romains vers entiers
    _ROMAN_MAP = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8}

    def _roman_to_int(self, roman: str) -> Optional[int]:
        """
        Convertit un chiffre romain simple en entier.

        Args:
            roman: Chiffre romain (I, II, III, IV, V, VI, VII, VIII).

        Returns:
            Entier correspondant, ou None si non reconnu.
        """
        return self._ROMAN_MAP.get(roman.upper())

    def _extract_part(self, result: dict[str, Any], title: str) -> tuple[Optional[int], str]:
        """
        Extrait le numero de partie depuis le resultat guessit ou le titre.

        Deux sources :
        1. Champ natif guessit `part` (detecte pour "Part N" anglais)
        2. Detection regex dans le titre parse (pour "Partie N", "Vol N", etc.)

        Args:
            result: Dictionnaire retourne par guessit.
            title: Titre deja extrait par _extract_title.

        Returns:
            Tuple (numero_de_partie, titre_nettoye).
            Si pas de partie detectee: (None, titre_inchange).
        """
        # Source 1 : champ natif guessit
        native_part = result.get("part")
        if native_part is not None:
            try:
                return (int(native_part), title)
            except (ValueError, TypeError):
                pass

        # Source 2 : detection regex dans le titre
        # Pattern "Partie N" (francais)
        match = re.search(r"\bPartie\s+(\d+)\b", title, re.IGNORECASE)
        if match:
            part_num = int(match.group(1))
            cleaned = title[: match.start()].rstrip() + title[match.end() :]
            return (part_num, cleaned.strip())

        # Pattern "Part N" (anglais, si guessit ne l'a pas extrait)
        match = re.search(r"\bPart\s+(\d+)\b", title, re.IGNORECASE)
        if match:
            part_num = int(match.group(1))
            cleaned = title[: match.start()].rstrip() + title[match.end() :]
            return (part_num, cleaned.strip())

        # Pattern "Vol N" / "Vol. N" / "Volume N" (chiffre arabe)
        match = re.search(r"\bVol(?:ume)?\.?\s*(\d+)\b", title, re.IGNORECASE)
        if match:
            part_num = int(match.group(1))
            cleaned = title[: match.start()].rstrip() + title[match.end() :]
            return (part_num, cleaned.strip())

        # Pattern "Vol I" / "Vol. II" / "Volume III" (chiffre romain)
        match = re.search(r"\bVol(?:ume)?\.?\s*([IVX]+)\b", title, re.IGNORECASE)
        if match:
            roman_val = self._roman_to_int(match.group(1))
            if roman_val is not None:
                cleaned = title[: match.start()].rstrip() + title[match.end() :]
                return (roman_val, cleaned.strip())

        return (None, title)

    def _extract_subtitle_language(self, result: dict[str, Any]) -> Optional[str]:
        """
        Extrait la langue des sous-titres depuis le resultat guessit.

        Guessit detecte "VOSTFR" comme subtitle_language=fr.

        Args:
            result: Dictionnaire retourne par guessit

        Returns:
            Code langue en majuscules (ex: "FR"), ou None
        """
        sub_lang = result.get("subtitle_language")
        if sub_lang is None:
            return None

        if isinstance(sub_lang, list):
            if len(sub_lang) == 0:
                return None
            sub_lang = sub_lang[0]

        try:
            return sub_lang.alpha2.upper()
        except AttributeError:
            return str(sub_lang).upper()
