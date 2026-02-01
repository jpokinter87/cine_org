"""
Service d'analyse du generique de fin pour identification automatique.

Utilise ffmpeg pour extraire les frames du generique, puis OCR (Tesseract
ou Claude Vision) pour lire le texte et comparer avec les candidats TMDB.
"""

import asyncio
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from loguru import logger


@dataclass
class CreditsAnalysisResult:
    """Resultat de l'analyse du generique."""

    detected_director: Optional[str] = None
    detected_actors: list[str] = None
    raw_text: str = ""
    confidence: float = 0.0
    method: str = "unknown"  # "tesseract" ou "claude"

    def __post_init__(self):
        if self.detected_actors is None:
            self.detected_actors = []


@dataclass
class CandidateMatch:
    """Correspondance entre l'analyse et un candidat."""

    candidate_id: str
    candidate_title: str
    candidate_year: Optional[int]
    match_score: float  # 0-100
    matched_director: bool
    matched_actors: list[str]


class CreditsAnalyzer:
    """
    Analyse le generique de fin d'un film pour identifier le bon candidat.

    Exemple d'utilisation:
        analyzer = CreditsAnalyzer()
        result = await analyzer.analyze(video_path)
        matches = analyzer.match_with_candidates(result, candidates_details)
    """

    # Patterns pour detecter realisateur et acteurs dans le texte OCR
    DIRECTOR_PATTERNS = [
        r"(?:directed by|director|realise par|realisateur|un film de|a film by)\s*[:\-]?\s*(.+)",
        r"(?:mise en scene|written and directed by)\s*[:\-]?\s*(.+)",
    ]

    ACTOR_PATTERNS = [
        r"(?:starring|avec|cast|acteurs|actors)\s*[:\-]?\s*(.+)",
    ]

    def __init__(
        self,
        anthropic_api_key: Optional[str] = None,
        prefer_claude: bool = False,
    ):
        """
        Initialise l'analyseur.

        Args:
            anthropic_api_key: Cle API pour Claude Vision (optionnel)
            prefer_claude: Si True, utilise Claude en priorite au lieu de Tesseract
        """
        self._api_key = anthropic_api_key
        self._prefer_claude = prefer_claude
        self._tesseract_available = self._check_tesseract()
        self._ffmpeg_available = self._check_ffmpeg()

    def _check_tesseract(self) -> bool:
        """Verifie si Tesseract est installe."""
        return shutil.which("tesseract") is not None

    def _check_ffmpeg(self) -> bool:
        """Verifie si ffmpeg est installe."""
        return shutil.which("ffmpeg") is not None

    def is_available(self) -> tuple[bool, str]:
        """
        Verifie si l'analyseur peut fonctionner.

        Returns:
            Tuple (disponible, message)
        """
        if not self._ffmpeg_available:
            return False, "ffmpeg non installe (sudo apt install ffmpeg)"

        if not self._tesseract_available and not self._api_key:
            return False, "Tesseract non installe (sudo apt install tesseract-ocr) et pas de cle API Claude"

        return True, "OK"

    async def analyze(
        self,
        video_path: Path,
        duration_seconds: Optional[int] = None,
    ) -> CreditsAnalysisResult:
        """
        Analyse le generique de fin d'un fichier video.

        Args:
            video_path: Chemin du fichier video
            duration_seconds: Duree totale en secondes (optionnel, detecte si absent)

        Returns:
            CreditsAnalysisResult avec le texte detecte
        """
        if not video_path.exists():
            logger.warning(f"Fichier non trouve: {video_path}")
            return CreditsAnalysisResult()

        # Extraire les frames du generique
        with tempfile.TemporaryDirectory() as tmpdir:
            frames_dir = Path(tmpdir)
            frames = await self._extract_credits_frames(video_path, frames_dir)

            if not frames:
                logger.warning("Aucune frame extraite du generique")
                return CreditsAnalysisResult()

            # OCR sur les frames
            if self._prefer_claude and self._api_key:
                result = await self._ocr_with_claude(frames)
            elif self._tesseract_available:
                result = await self._ocr_with_tesseract(frames)
                # Si confiance faible et Claude dispo, essayer Claude
                if result.confidence < 50 and self._api_key:
                    logger.info("Confiance Tesseract faible, essai avec Claude Vision")
                    result = await self._ocr_with_claude(frames)
            elif self._api_key:
                result = await self._ocr_with_claude(frames)
            else:
                return CreditsAnalysisResult()

            # Extraire realisateur et acteurs du texte brut
            result.detected_director = self._extract_director(result.raw_text)
            result.detected_actors = self._extract_actors(result.raw_text)

            return result

    async def _extract_credits_frames(
        self,
        video_path: Path,
        output_dir: Path,
        num_frames: int = 8,
        credits_duration: int = 120,  # 2 minutes de generique
    ) -> list[Path]:
        """
        Extrait les frames du generique de fin.

        Args:
            video_path: Chemin du fichier video
            output_dir: Repertoire de sortie
            num_frames: Nombre de frames a extraire
            credits_duration: Duree du generique a analyser (secondes)

        Returns:
            Liste des chemins des frames extraites
        """
        if not self._ffmpeg_available:
            return []

        output_pattern = output_dir / "frame_%03d.jpg"

        # Extraire les frames des 2 dernieres minutes (generique)
        # -sseof : position depuis la fin
        cmd = [
            "ffmpeg",
            "-sseof", f"-{credits_duration}",
            "-i", str(video_path),
            "-vf", f"fps=1/{credits_duration // num_frames}",  # 1 frame tous les X secondes
            "-q:v", "2",  # Qualite JPEG
            "-frames:v", str(num_frames),
            str(output_pattern),
            "-y",  # Ecraser
            "-loglevel", "error",
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=60)

            if process.returncode != 0:
                logger.warning(f"ffmpeg erreur: {stderr.decode()}")
                return []

            # Lister les frames extraites
            frames = sorted(output_dir.glob("frame_*.jpg"))
            logger.debug(f"Extrait {len(frames)} frames du generique")
            return frames

        except asyncio.TimeoutError:
            logger.warning("Timeout extraction ffmpeg")
            return []
        except Exception as e:
            logger.warning(f"Erreur extraction frames: {e}")
            return []

    async def _ocr_with_tesseract(self, frames: list[Path]) -> CreditsAnalysisResult:
        """
        OCR avec Tesseract (gratuit, local).

        Args:
            frames: Liste des frames a analyser

        Returns:
            CreditsAnalysisResult
        """
        try:
            import pytesseract
            from PIL import Image, ImageEnhance, ImageFilter
        except ImportError:
            logger.warning("pytesseract ou PIL non installe")
            return CreditsAnalysisResult(method="tesseract")

        all_text = []
        for frame_path in frames:
            try:
                # Charger et preprocesser l'image pour ameliorer l'OCR
                img = Image.open(frame_path)

                # Convertir en niveaux de gris
                img = img.convert("L")

                # Augmenter le contraste
                enhancer = ImageEnhance.Contrast(img)
                img = enhancer.enhance(2.0)

                # OCR avec langues francais + anglais
                text = pytesseract.image_to_string(img, lang="fra+eng")
                if text.strip():
                    all_text.append(text)

            except Exception as e:
                logger.debug(f"Erreur OCR frame {frame_path}: {e}")
                continue

        combined_text = "\n".join(all_text)

        # Estimer la confiance basee sur la quantite de texte lisible
        word_count = len(combined_text.split())
        confidence = min(100, word_count * 2)  # ~50 mots = 100% confiance

        return CreditsAnalysisResult(
            raw_text=combined_text,
            confidence=confidence,
            method="tesseract",
        )

    async def _ocr_with_claude(self, frames: list[Path]) -> CreditsAnalysisResult:
        """
        OCR avec Claude Vision (plus precis, payant).

        Args:
            frames: Liste des frames a analyser

        Returns:
            CreditsAnalysisResult
        """
        if not self._api_key:
            return CreditsAnalysisResult(method="claude")

        try:
            import anthropic
            import base64
        except ImportError:
            logger.warning("anthropic non installe")
            return CreditsAnalysisResult(method="claude")

        # Selectionner les meilleures frames (milieu du generique)
        selected_frames = frames[len(frames) // 4 : len(frames) * 3 // 4]
        if not selected_frames:
            selected_frames = frames[:3]

        # Encoder les images en base64
        images_content = []
        for frame_path in selected_frames[:4]:  # Max 4 images
            with open(frame_path, "rb") as f:
                image_data = base64.standard_b64encode(f.read()).decode("utf-8")
                images_content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": image_data,
                    },
                })

        # Ajouter le prompt
        images_content.append({
            "type": "text",
            "text": """Analyse ce generique de film et extrait les informations suivantes:
1. Le nom du realisateur (directed by, realise par, un film de)
2. Les noms des acteurs principaux

Reponds uniquement avec le format:
REALISATEUR: [nom]
ACTEURS: [nom1], [nom2], [nom3]

Si tu ne trouves pas d'information, indique "Non trouve"."""
        })

        try:
            client = anthropic.Anthropic(api_key=self._api_key)
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                messages=[{
                    "role": "user",
                    "content": images_content,
                }],
            )

            raw_text = response.content[0].text
            return CreditsAnalysisResult(
                raw_text=raw_text,
                confidence=90,  # Claude est generalement fiable
                method="claude",
            )

        except Exception as e:
            logger.warning(f"Erreur Claude Vision: {e}")
            return CreditsAnalysisResult(method="claude")

    def _extract_director(self, text: str) -> Optional[str]:
        """Extrait le nom du realisateur du texte OCR."""
        text_lower = text.lower()

        # Pattern Claude Vision
        match = re.search(r"realisateur\s*:\s*(.+)", text_lower)
        if match:
            name = match.group(1).strip()
            if name and name != "non trouve":
                return self._clean_name(name)

        # Patterns generiques
        for pattern in self.DIRECTOR_PATTERNS:
            match = re.search(pattern, text_lower)
            if match:
                return self._clean_name(match.group(1))

        return None

    def _extract_actors(self, text: str) -> list[str]:
        """Extrait les noms des acteurs du texte OCR."""
        text_lower = text.lower()
        actors = []

        # Pattern Claude Vision
        match = re.search(r"acteurs\s*:\s*(.+)", text_lower)
        if match:
            actors_str = match.group(1).strip()
            if actors_str and actors_str != "non trouve":
                actors = [self._clean_name(a) for a in actors_str.split(",")]

        # Si pas trouve, essayer les patterns generiques
        if not actors:
            for pattern in self.ACTOR_PATTERNS:
                match = re.search(pattern, text_lower)
                if match:
                    actors_str = match.group(1)
                    actors = [self._clean_name(a) for a in actors_str.split(",")]
                    break

        return [a for a in actors if a]  # Filtrer les vides

    def _clean_name(self, name: str) -> str:
        """Nettoie un nom extrait."""
        # Retirer les caracteres speciaux et normaliser
        name = re.sub(r"[^\w\s\-']", "", name)
        name = " ".join(name.split())  # Normaliser espaces
        return name.strip().title()

    def match_with_candidates(
        self,
        analysis: CreditsAnalysisResult,
        candidates_details: list[dict],
    ) -> list[CandidateMatch]:
        """
        Compare l'analyse avec les candidats TMDB.

        Args:
            analysis: Resultat de l'analyse OCR
            candidates_details: Liste des candidats avec leurs details TMDB
                Chaque dict doit avoir: id, title, year, director, actors

        Returns:
            Liste des correspondances triees par score decroissant
        """
        if not analysis.detected_director and not analysis.detected_actors:
            return []

        matches = []
        for candidate in candidates_details:
            score = 0.0
            matched_director = False
            matched_actors = []

            # Comparer le realisateur (50 points)
            if analysis.detected_director and candidate.get("director"):
                if self._names_match(
                    analysis.detected_director, candidate["director"]
                ):
                    score += 50
                    matched_director = True

            # Comparer les acteurs (50 points max, 10 par acteur)
            if analysis.detected_actors and candidate.get("actors"):
                candidate_actors = candidate["actors"]
                for detected_actor in analysis.detected_actors:
                    for cand_actor in candidate_actors:
                        if self._names_match(detected_actor, cand_actor):
                            score += 10
                            matched_actors.append(detected_actor)
                            break
                score = min(score, 100)  # Plafonner a 100

            if score > 0:
                matches.append(CandidateMatch(
                    candidate_id=candidate.get("id", ""),
                    candidate_title=candidate.get("title", ""),
                    candidate_year=candidate.get("year"),
                    match_score=score,
                    matched_director=matched_director,
                    matched_actors=matched_actors,
                ))

        # Trier par score decroissant
        matches.sort(key=lambda m: m.match_score, reverse=True)
        return matches

    def _names_match(self, name1: str, name2: str) -> bool:
        """Verifie si deux noms correspondent (fuzzy match)."""
        # Normaliser
        n1 = name1.lower().strip()
        n2 = name2.lower().strip()

        # Match exact
        if n1 == n2:
            return True

        # Match partiel (nom de famille)
        parts1 = n1.split()
        parts2 = n2.split()

        # Verifier si le nom de famille correspond
        if parts1 and parts2:
            if parts1[-1] == parts2[-1]:  # Meme nom de famille
                return True

        # Verifier si un nom est contenu dans l'autre
        if n1 in n2 or n2 in n1:
            return True

        return False
