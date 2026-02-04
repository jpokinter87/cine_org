"""
Service d'analyse du generique de fin pour identification automatique.

Utilise ffmpeg pour extraire les frames du generique, puis OCR (Tesseract
ou Claude Vision) pour lire le texte et comparer avec les candidats TMDB.
"""

import asyncio
import json
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
        self._easyocr_available = self._check_easyocr()
        self._tesseract_available = self._check_tesseract()
        self._ffmpeg_available = self._check_ffmpeg()
        self._easyocr_reader = None  # Initialise a la demande (lent)

    def _check_easyocr(self) -> bool:
        """Verifie si EasyOCR est installe."""
        try:
            import easyocr
            return True
        except ImportError:
            return False

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

        if not self._easyocr_available and not self._tesseract_available and not self._api_key:
            return False, "Aucun OCR disponible (pip install easyocr ou sudo apt install tesseract-ocr)"

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

            # OCR sur les frames (priorite: Tesseract > EasyOCR > Claude)
            # Tesseract est rapide, EasyOCR plus precis mais lent
            if self._prefer_claude and self._api_key:
                result = await self._ocr_with_claude(frames)
            elif self._tesseract_available:
                result = await self._ocr_with_tesseract(frames)
                # Si confiance faible, essayer EasyOCR ou Claude
                if result.confidence < 50:
                    if self._easyocr_available:
                        logger.info("Confiance Tesseract faible, essai avec EasyOCR")
                        result = await self._ocr_with_easyocr(frames)
                    elif self._api_key:
                        logger.info("Confiance Tesseract faible, essai avec Claude Vision")
                        result = await self._ocr_with_claude(frames)
            elif self._easyocr_available:
                result = await self._ocr_with_easyocr(frames)
            elif self._api_key:
                result = await self._ocr_with_claude(frames)
            else:
                return CreditsAnalysisResult()

            return result

    async def _get_last_chapter_start(self, video_path: Path) -> Optional[float]:
        """
        Recupere le timestamp de debut du dernier chapitre (generique).

        Args:
            video_path: Chemin du fichier video

        Returns:
            Timestamp en secondes du debut du dernier chapitre, ou None
        """
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_chapters",
            str(video_path),
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=30)

            if process.returncode != 0:
                return None

            data = json.loads(stdout.decode())
            chapters = data.get("chapters", [])

            if not chapters:
                return None

            # Dernier chapitre = generique de fin
            last_chapter = chapters[-1]
            start_time = float(last_chapter.get("start_time", 0))

            logger.debug(
                f"Dernier chapitre: {last_chapter.get('tags', {}).get('title', '?')} "
                f"a {start_time:.1f}s"
            )
            return start_time

        except Exception as e:
            logger.debug(f"Impossible de lire les chapitres: {e}")
            return None

    async def _extract_credits_frames(
        self,
        video_path: Path,
        output_dir: Path,
        frame_interval: int = 8,  # 1 frame toutes les 8 secondes (duree defilement)
        credits_duration: int = 300,  # 5 minutes de generique
    ) -> list[Path]:
        """
        Extrait les frames du generique de fin.

        Utilise les chapitres si disponibles pour trouver le debut exact
        du generique, sinon utilise les dernieres minutes du film.

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

        # Essayer de trouver le debut du generique via les chapitres
        chapter_start = await self._get_last_chapter_start(video_path)

        # Calculer le nombre de frames a extraire
        num_frames = credits_duration // frame_interval

        if chapter_start is not None:
            # Utiliser le debut du dernier chapitre
            logger.debug(
                f"Extraction depuis le chapitre a {chapter_start:.1f}s "
                f"({num_frames} frames, 1 toutes les {frame_interval}s)"
            )
            cmd = [
                "ffmpeg",
                "-ss", str(chapter_start),
                "-i", str(video_path),
                "-vf", f"fps=1/{frame_interval}",
                "-q:v", "2",
                "-frames:v", str(num_frames),
                str(output_pattern),
                "-y",
                "-loglevel", "error",
            ]
        else:
            # Fallback: utiliser les dernieres minutes du film
            logger.debug(
                f"Pas de chapitres, extraction des {credits_duration}s finales "
                f"({num_frames} frames, 1 toutes les {frame_interval}s)"
            )
            cmd = [
                "ffmpeg",
                "-sseof", f"-{credits_duration}",
                "-i", str(video_path),
                "-vf", f"fps=1/{frame_interval}",
                "-q:v", "2",
                "-frames:v", str(num_frames),
                str(output_pattern),
                "-y",
                "-loglevel", "error",
            ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=120)

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
                # Charger l'image
                img = Image.open(frame_path)

                # Upscaler si basse resolution (720p ou moins)
                if img.height < 800:
                    scale_factor = 2
                    img = img.resize(
                        (img.width * scale_factor, img.height * scale_factor),
                        Image.Resampling.LANCZOS
                    )

                # Convertir en niveaux de gris
                img = img.convert("L")

                # Augmenter le contraste
                enhancer = ImageEnhance.Contrast(img)
                img = enhancer.enhance(2.0)

                # Binarisation avec seuil adaptatif (Otsu-like)
                pixels = list(img.getdata())
                threshold = sum(pixels) // len(pixels)
                img = img.point(lambda p: 255 if p > threshold else 0)

                # Detecter si texte clair sur fond sombre (inverser si necessaire)
                white_pixels = sum(1 for p in img.getdata() if p > 127)
                if white_pixels < len(pixels) // 2:
                    img = img.point(lambda p: 255 - p)

                # OCR avec langues francais + anglais
                # PSM 6 = bloc de texte uniforme (bon pour generiques)
                text = pytesseract.image_to_string(
                    img, lang="fra+eng",
                    config="--psm 6"
                )
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

    async def _ocr_with_easyocr(self, frames: list[Path]) -> CreditsAnalysisResult:
        """
        OCR avec EasyOCR (deep learning, meilleur sur polices stylisees).

        Args:
            frames: Liste des frames a analyser

        Returns:
            CreditsAnalysisResult
        """
        try:
            import easyocr
        except ImportError:
            logger.warning("easyocr non installe")
            return CreditsAnalysisResult(method="easyocr")

        # Initialiser le reader une seule fois (lent au premier appel)
        if self._easyocr_reader is None:
            logger.debug("Initialisation EasyOCR (peut prendre quelques secondes)...")
            self._easyocr_reader = easyocr.Reader(
                ["fr", "en"],
                gpu=False,  # CPU par defaut, plus compatible
                verbose=False
            )

        all_text = []
        for frame_path in frames:
            try:
                # EasyOCR accepte directement le chemin de l'image
                results = self._easyocr_reader.readtext(str(frame_path))

                # Extraire le texte de chaque detection
                for (bbox, text, confidence) in results:
                    if confidence > 0.3:  # Seuil de confiance minimum
                        all_text.append(text)

            except Exception as e:
                logger.debug(f"Erreur EasyOCR frame {frame_path}: {e}")
                continue

        combined_text = "\n".join(all_text)

        # Estimer la confiance basee sur la quantite de texte lisible
        word_count = len(combined_text.split())
        confidence = min(100, word_count * 2)  # ~50 mots = 100% confiance

        return CreditsAnalysisResult(
            raw_text=combined_text,
            confidence=confidence,
            method="easyocr",
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

    def match_with_candidates(
        self,
        analysis: CreditsAnalysisResult,
        candidates_details: list[dict],
    ) -> list[CandidateMatch]:
        """
        Compare le texte OCR avec le casting des candidats TMDB.

        Approche generique : cherche les noms du casting (realisateur + acteurs)
        directement dans le texte brut OCR, independamment du format du generique.

        Args:
            analysis: Resultat de l'analyse OCR (contient raw_text)
            candidates_details: Liste des candidats avec leurs details TMDB
                Chaque dict doit avoir: id, title, year, director, actors

        Returns:
            Liste des correspondances triees par score decroissant
        """
        if not analysis.raw_text:
            return []

        # Verifier la qualite du texte OCR (trop de bruit = inutilisable)
        raw = analysis.raw_text
        alpha_count = sum(1 for c in raw if c.isalpha())
        noise_ratio = 1 - (alpha_count / len(raw)) if raw else 1
        if noise_ratio > 0.7:
            # Plus de 70% de caracteres non-alphabetiques = bruit
            logger.debug(f"Texte OCR trop bruite ({noise_ratio:.0%} de bruit)")
            return []

        # Normaliser le texte OCR pour la recherche
        ocr_text = analysis.raw_text.lower()

        matches = []
        for candidate in candidates_details:
            matched_director = False
            matched_actors = []

            # Chercher le realisateur dans le texte OCR
            director = candidate.get("director", "")
            if director and self._name_in_text(director, ocr_text):
                matched_director = True

            # Chercher les acteurs dans le texte OCR
            actors = candidate.get("actors", [])
            for actor in actors:
                if self._name_in_text(actor, ocr_text):
                    matched_actors.append(actor)

            # Calculer le score: 50 pts realisateur + 10 pts par acteur (max 50)
            score = 0.0
            if matched_director:
                score += 50
            score += min(len(matched_actors) * 10, 50)

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

    def _name_in_text(self, name: str, text: str) -> bool:
        """
        Verifie si un nom est present dans le texte OCR.

        Cherche le nom complet ou au moins le nom de famille.
        Tolerant aux erreurs OCR mineures.

        Args:
            name: Nom a chercher (ex: "Joanna Kulig")
            text: Texte OCR normalise (lowercase)

        Returns:
            True si le nom est trouve
        """
        name_lower = name.lower().strip()

        # Match exact du nom complet (comme mot entier)
        # Utiliser une regex pour eviter les matchs partiels
        if re.search(r'\b' + re.escape(name_lower) + r'\b', text):
            return True

        # Essayer avec le nom de famille seul (dernier mot)
        parts = name_lower.split()
        if len(parts) >= 2:
            surname = parts[-1]
            # Le nom de famille doit avoir au moins 5 caracteres pour eviter les faux positifs
            # (exclut Lee, Kot, etc. qui matchent trop facilement dans du bruit)
            if len(surname) >= 5 and re.search(r'\b' + re.escape(surname) + r'\b', text):
                return True

        return False
