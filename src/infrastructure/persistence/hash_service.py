"""
Service de calcul de hash XXHash par echantillons.

Ce service calcule un hash rapide pour les fichiers video en utilisant
un algorithme d'echantillonnage plutot qu'une lecture complete du fichier.

Algorithme :
    1. Lit les premiers SAMPLE_SIZE octets (debut du fichier)
    2. Si le fichier est assez grand, lit les derniers SAMPLE_SIZE octets (fin du fichier)
    3. Ajoute la taille du fichier au hash

Cette approche est suffisante pour la detection de doublons car :
    - Les headers video contiennent des metadonnees uniques (codec, resolution, etc.)
    - Les derniers octets contiennent souvent des index ou signatures
    - La taille complete du fichier ajoute une dimension supplementaire
    - Deux fichiers video differents avec meme debut/fin/taille est extremement improbable

Performance : ~10x plus rapide que MD5/SHA sur les gros fichiers (2 Mo lus max au lieu de tout le fichier)
"""

import os
from pathlib import Path

import xxhash

# Taille de l'echantillon : 1 Mo
SAMPLE_SIZE = 1024 * 1024  # 1 Mo


def compute_file_hash(file_path: Path, sample_size: int = SAMPLE_SIZE) -> str:
    """
    Calcule un hash XXH3-64 par echantillonnage du fichier.

    L'algorithme hash le debut, la fin (si fichier assez grand) et la taille
    du fichier pour generer une empreinte rapide mais fiable.

    Args :
        file_path : Chemin vers le fichier a hasher
        sample_size : Taille de chaque echantillon en octets (defaut 1 Mo)

    Retourne :
        Hash hexadecimal de 16 caracteres (xxh3_64)

    Raises :
        FileNotFoundError : Si le fichier n'existe pas
        PermissionError : Si le fichier n'est pas lisible
    """
    hasher = xxhash.xxh3_64()
    file_size = file_path.stat().st_size

    with open(file_path, "rb") as f:
        # Hash le debut du fichier
        start_data = f.read(sample_size)
        hasher.update(start_data)

        # Si fichier assez grand, hash aussi la fin
        if file_size > 2 * sample_size:
            f.seek(-sample_size, os.SEEK_END)
            end_data = f.read(sample_size)
            hasher.update(end_data)

        # Hash la taille du fichier pour ajouter une dimension
        hasher.update(str(file_size).encode())

    return hasher.hexdigest()
