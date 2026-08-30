"""Tests pour strip_trailing_year (utils.helpers).

Retire une année « (AAAA) » en fin de titre pour éviter la double année dans
les chemins/noms de fichiers (ex. « Surface (2025) (2025) »).
"""

from src.utils.helpers import strip_trailing_year


def test_retire_annee_finale():
    assert strip_trailing_year("Surface (2025)") == "Surface"


def test_sans_annee_inchange():
    assert strip_trailing_year("Detectorists") == "Detectorists"


def test_espaces_finaux_nettoyes():
    assert strip_trailing_year("Surface (2025)  ") == "Surface"


def test_parenthese_non_annee_conservee():
    assert strip_trailing_year("Archer (2009) Vice") == "Archer (2009) Vice"


def test_annee_au_milieu_conservee():
    # Seule une année strictement finale est retirée.
    assert strip_trailing_year("Blade Runner 2049") == "Blade Runner 2049"


def test_titre_vide():
    assert strip_trailing_year("") == ""
