"""
Fonctions utilitaires pour la reparation de symlinks.

Fournit l'extraction de noms de series depuis les chemins
et l'affichage des informations de symlinks casses.
"""

from pathlib import Path
from typing import Optional

from rich.panel import Panel


def extract_series_name(path: Path) -> Optional[str]:
    """
    Extrait le nom de la serie depuis le chemin du symlink.

    Analyse le chemin pour trouver le nom de la serie en ignorant
    les subdivisions alphabetiques, les types de series et les
    sous-genres documentaires (mots simples comme Science, Geographie...).

    Args:
        path: Chemin du symlink

    Returns:
        Le nom de la serie ou None si pas trouve
    """
    parts = path.parts
    for i, part in enumerate(parts):
        if part.lower() in ("séries", "series"):
            # Le nom de la serie est generalement 2-3 niveaux apres
            # Ex: Séries/Séries TV/A-M/Breaking Bad/Saison 01/...
            is_documentary = False
            for j in range(i + 1, min(i + 7, len(parts))):
                # Ignorer les subdivisions alphabetiques et types connus
                if parts[j] in ("Séries TV", "Animation", "Mangas"):
                    continue
                if parts[j].startswith(("Animation ", "Mangas ")):
                    continue
                # Categorie documentaire : activer le filtrage des sous-genres
                if parts[j].startswith("Séries "):
                    is_documentary = True
                    continue
                if len(parts[j]) <= 3 and ("-" in parts[j] or len(parts[j]) == 1):
                    continue  # Subdivision A-M, lettre unique, etc.
                if parts[j].startswith("Saison"):
                    break
                # Sous-genres documentaires : mots simples sans espace ni chiffre
                if is_documentary and " " not in parts[j] and not any(c.isdigit() for c in parts[j]):
                    continue
                return parts[j]
    return None


def display_broken_link_info(console, link: Path) -> None:
    """
    Affiche les informations d'un symlink casse.

    Args:
        console: Console Rich pour l'affichage
        link: Chemin du symlink casse
    """
    try:
        original_target = link.readlink()
    except OSError:
        original_target = Path("<inconnu>")

    panel_content = [
        f"[bold]{link.name}[/bold]",
        f"Chemin: {link}",
        f"Cible originale: [red]{original_target}[/red]",
    ]
    console.print(Panel("\n".join(panel_content), title="Symlink casse"))
