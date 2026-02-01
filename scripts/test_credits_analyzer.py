#!/usr/bin/env python3
"""
Script de test pour le module CreditsAnalyzer.

Usage:
    python scripts/test_credits_analyzer.py /chemin/vers/Cold.War.2018.mkv

Prérequis:
    - ffmpeg installé: sudo apt install ffmpeg
    - tesseract installé: sudo apt install tesseract-ocr tesseract-ocr-fra
    - Ou variable ANTHROPIC_API_KEY définie pour utiliser Claude Vision
"""

import asyncio
import os
import sys
from pathlib import Path

# Ajouter le répertoire src au path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.services.credits_analyzer import CreditsAnalyzer, CreditsAnalysisResult


# Candidats simulés pour Cold War (2018) - données TMDB
COLD_WAR_CANDIDATES = [
    {
        "id": "467188",
        "title": "Cold War",
        "year": 2018,
        "director": "Paweł Pawlikowski",
        "actors": ["Joanna Kulig", "Tomasz Kot", "Borys Szyc", "Agata Kulesza"],
    },
    {
        "id": "408508",
        "title": "Guerre froide",
        "year": 2017,
        "director": "J. Wilder Konschak",
        "actors": ["Tyrese Gibson", "50 Cent"],
    },
]


async def test_credits_analyzer(video_path: Path, use_claude: bool = False):
    """Test complet de l'analyseur de crédits."""

    print("=" * 60)
    print("TEST CREDITS ANALYZER")
    print("=" * 60)
    print(f"\nFichier: {video_path}")
    print(f"Existe: {video_path.exists()}")

    if not video_path.exists():
        print("\n❌ ERREUR: Fichier non trouvé!")
        return

    # Récupérer la clé API si disponible
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    # Créer l'analyseur
    analyzer = CreditsAnalyzer(
        anthropic_api_key=api_key,
        prefer_claude=use_claude,
    )

    # Vérifier la disponibilité
    available, message = analyzer.is_available()
    print(f"\nAnalyseur disponible: {available}")
    print(f"Message: {message}")

    if not available:
        print("\n❌ Analyseur non disponible!")
        return

    # Lancer l'analyse
    print("\n" + "-" * 40)
    print("EXTRACTION DES FRAMES...")
    print("-" * 40)

    result = await analyzer.analyze(video_path)

    print("\n" + "-" * 40)
    print("RÉSULTAT DE L'ANALYSE OCR")
    print("-" * 40)
    print(f"Méthode utilisée: {result.method}")
    print(f"Confiance OCR: {result.confidence}%")

    if result.raw_text:
        print(f"\nTexte brut extrait (premiers 800 chars):")
        print("-" * 40)
        print(result.raw_text[:800])

    # Comparer avec les candidats
    print("\n" + "-" * 40)
    print("CORRESPONDANCE AVEC LES CANDIDATS")
    print("-" * 40)

    matches = analyzer.match_with_candidates(result, COLD_WAR_CANDIDATES)

    if not matches:
        print("❌ Aucune correspondance trouvée")
    else:
        for i, match in enumerate(matches, 1):
            print(f"\n{i}. {match.candidate_title} ({match.candidate_year})")
            print(f"   Score: {match.match_score}%")
            print(f"   Réalisateur trouvé: {'✓' if match.matched_director else '✗'}")
            print(f"   Acteurs trouvés: {', '.join(match.matched_actors) if match.matched_actors else 'Aucun'}")

        # Recommandation
        # 3+ acteurs OU realisateur + 1 acteur = match fiable
        best = matches[0]
        num_actors = len(best.matched_actors)
        is_reliable = (
            num_actors >= 3 or
            (best.matched_director and num_actors >= 1) or
            best.match_score >= 50
        )

        if is_reliable:
            print(f"\n✓ RECOMMANDATION: {best.candidate_title} ({best.candidate_year})")
            print(f"  Confiance: {best.match_score}% ({num_actors} acteurs trouvés)")
        else:
            print("\n⚠ Aucune correspondance assez fiable")


def main():
    """Point d'entrée du script."""

    if len(sys.argv) < 2:
        print(__doc__)
        print("\nExemple:")
        print("  python scripts/test_credits_analyzer.py /path/to/Cold.War.2018.mkv")
        print("\nOptions:")
        print("  --claude    Forcer l'utilisation de Claude Vision au lieu de Tesseract")
        sys.exit(1)

    video_path = Path(sys.argv[1])
    use_claude = "--claude" in sys.argv

    asyncio.run(test_credits_analyzer(video_path, use_claude))


if __name__ == "__main__":
    main()
