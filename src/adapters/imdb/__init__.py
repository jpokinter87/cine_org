"""
Adaptateurs pour les datasets IMDb.

Ce module fournit:
- TSVParser: Parser pour les fichiers TSV compresses (title.ratings.tsv.gz, etc.)
- IMDbDatasetImporter: Gestionnaire de telechargement et import des datasets
"""

from .dataset_importer import IMDbDatasetImporter, IMDbDatasetStats
from .tsv_parser import TSVParser

__all__ = ["TSVParser", "IMDbDatasetImporter", "IMDbDatasetStats"]
