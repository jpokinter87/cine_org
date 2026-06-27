"""Tests unitaires pour MovieFileFinder.

Tier 1 : symlink formaté existant dans video_dir.
Tier 2 : recherche storage + scoring canonique titre/année/durée (seuil 85).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.core.entities.media import Movie
from src.core.value_objects.media_info import MediaInfo
from src.adapters.parsing.guessit_parser import GuessitFilenameParser
from src.services.relink_service import MovieFileFinder


@pytest.fixture
def parser():
    return GuessitFilenameParser()


@pytest.fixture
def video_dir(tmp_path):
    d = tmp_path / "video"
    (d / "Films" / "Action & Aventure").mkdir(parents=True)
    (d / "Films" / "Drame").mkdir(parents=True)
    return d


@pytest.fixture
def storage_dir(tmp_path):
    d = tmp_path / "storage"
    (d / "Films" / "Drame").mkdir(parents=True)
    return d


def _extractor(duration_seconds):
    """Extracteur renvoyant un MediaInfo avec seulement la durée."""
    ext = MagicMock()
    ext.extract.return_value = MediaInfo(duration_seconds=duration_seconds)
    return ext


def test_tier1_returns_existing_symlink_when_target_valid(
    video_dir, storage_dir, parser
):
    """Tier 1 : symlink formaté présent + cible valide → réutilisé, pas de scoring."""
    (storage_dir / "Films" / "Action & Aventure").mkdir(parents=True)
    target = (
        storage_dir
        / "Films"
        / "Action & Aventure"
        / "Die Hard 4 - Retour en enfer (2007) MULTi x265 1080p.mkv"
    )
    target.write_bytes(b"fake")
    link = video_dir / "Films" / "Action & Aventure" / target.name
    link.symlink_to(target)

    repair = MagicMock()
    finder = MovieFileFinder(
        video_dir=video_dir,
        repair_service=repair,
        parser=parser,
        media_info_extractor=_extractor(8000),
    )

    movie = Movie(
        title="Die Hard 4 : Retour en enfer",
        original_title="Live Free or Die Hard",
        year=2007,
        genres=("Action & Aventure",),
    )
    found = finder.find(movie)

    assert found is not None
    assert found.existing_symlink == link
    assert found.storage_path.resolve() == target.resolve()
    repair.find_possible_targets.assert_not_called()


def test_tier2_accepts_when_title_year_duration_match(video_dir, storage_dir, parser):
    """Tier 2 : titre + année + durée concordants → accepté."""
    raw = storage_dir / "Films" / "Drame" / "cria.cuervos.1976.multi.1080p.x264.mkv"
    raw.write_bytes(b"fake")

    repair = MagicMock()
    repair.find_possible_targets.return_value = [(raw, 50.0)]
    # Durée fichier ≈ durée déclarée (6300 s)
    finder = MovieFileFinder(
        video_dir=video_dir,
        repair_service=repair,
        parser=parser,
        media_info_extractor=_extractor(6400),
    )

    movie = Movie(
        title="Cría cuervos",
        original_title="Cría cuervos",
        year=1976,
        genres=("Drame",),
        duration_seconds=6300,
    )
    found = finder.find(movie)

    assert found is not None
    assert found.existing_symlink is None
    assert found.storage_path == raw


def test_tier2_rejects_matching_title_year_but_wrong_duration(
    video_dir, storage_dir, parser
):
    """Tier 2 : titre + année identiques mais durée incohérente → rejeté.

    Garde-fou durée : sans elle le score serait 100 (titre+année exacts).
    """
    raw = storage_dir / "Films" / "Drame" / "Le Film (2005) x264.mkv"
    raw.write_bytes(b"fake")

    repair = MagicMock()
    repair.find_possible_targets.return_value = [(raw, 95.0)]
    # Fiche : 25 min déclarés ; fichier : 100 min → incohérent
    finder = MovieFileFinder(
        video_dir=video_dir,
        repair_service=repair,
        parser=parser,
        media_info_extractor=_extractor(6000),
    )

    movie = Movie(title="Le Film", year=2005, genres=("Drame",), duration_seconds=1500)
    assert finder.find(movie) is None


def test_tier2_rejects_featurette_much_shorter_than_film(
    video_dir, storage_dir, parser
):
    """Tier 2 : featurette (38 min) ne se lie pas au film principal (143 min)."""
    raw = (
        storage_dir
        / "Films"
        / "Drame"
        / "Pirates.of.the.Caribbean.The.Curse.of.the.Black.Pearl.2003.x264.mkv"
    )
    raw.write_bytes(b"fake")

    repair = MagicMock()
    repair.find_possible_targets.return_value = [(raw, 80.0)]
    finder = MovieFileFinder(
        video_dir=video_dir,
        repair_service=repair,
        parser=parser,
        media_info_extractor=_extractor(8580),  # 143 min
    )

    movie = Movie(
        title="An Epic At Sea: The Making of Pirates of the Caribbean",
        year=2003,
        genres=("Drame",),
        duration_seconds=2280,  # 38 min
    )
    assert finder.find(movie) is None


def test_tier2_canonical_filename_title_not_truncated_by_separator(
    video_dir, storage_dir, parser
):
    """Tier 2 : un nom déjà canonique avec « - » n'est pas tronqué par guessit.

    « Dragons 3 - Le monde caché (2019)… » : guessit ne garde que « Dragons 3 ».
    On doit retomber sur le titre complet (avant « (année) ») pour scorer juste.
    """
    raw = (
        storage_dir
        / "Films"
        / "Drame"
        / "Dragons 3 - Le monde caché (2019) MULTi x265 1080p.mkv"
    )
    raw.write_bytes(b"fake")

    repair = MagicMock()
    repair.find_possible_targets.return_value = [(raw, 50.0)]
    finder = MovieFileFinder(
        video_dir=video_dir,
        repair_service=repair,
        parser=parser,
        media_info_extractor=_extractor(6240),  # 104 min ≈ 97 min déclarés
    )

    movie = Movie(
        title="Dragons 3 : Le monde caché",
        year=2019,
        genres=("Drame",),
        duration_seconds=5820,  # 97 min
    )
    found = finder.find(movie)

    assert found is not None
    assert found.storage_path == raw


def test_suggest_returns_borderline_candidates_excluding_safe(
    video_dir, storage_dir, parser
):
    """suggest() ne propose que la bande litigieuse (floor ≤ score < seuil).

    Titre+année exacts (base 75). Durée pilote le score :
    - durée concordante → 100 (lien sûr, exclu des suggestions)
    - durée très incohérente → 75 (bande litigieuse, proposé)
    """
    safe = storage_dir / "Films" / "Drame" / "Le Film (2005) SAFE.mkv"
    safe.write_bytes(b"fake")
    band = storage_dir / "Films" / "Drame" / "Le Film (2005) BAND.mkv"
    band.write_bytes(b"fake")

    repair = MagicMock()
    repair.find_possible_targets.return_value = [(safe, 50.0), (band, 50.0)]

    ext = MagicMock()

    def _extract(path):
        dur = 6000 if "SAFE" in str(path) else 12000  # band = 2× la durée déclarée
        return MediaInfo(duration_seconds=dur)

    ext.extract.side_effect = _extract

    finder = MovieFileFinder(
        video_dir=video_dir,
        repair_service=repair,
        parser=parser,
        media_info_extractor=ext,
        min_score=85.0,
    )

    movie = Movie(title="Le Film", year=2005, genres=("Drame",), duration_seconds=6000)

    # find() prend le lien sûr (≥85)
    found = finder.find(movie)
    assert found is not None and found.storage_path == safe

    # suggest() ne propose que la bande litigieuse, pas le lien sûr
    suggestions = finder.suggest(movie, floor=60.0)
    paths = [s.storage_path for s in suggestions]
    assert band in paths
    assert safe not in paths
    assert all(60.0 <= s.score < 85.0 for s in suggestions)


def test_tier2_uses_alternative_titles_to_find_internationally_named_file(
    video_dir, storage_dir, parser
):
    """Tier 2 : un titre AKA (TMDB) permet de retrouver un fichier au titre international.

    « Ukryta gra » (titre DB) est rangé sous « The Coldest Game » dans storage :
    sans titre alternatif, introuvable ; avec, il remonte et score haut.
    """
    coldest = storage_dir / "Films" / "Drame" / "The Coldest Game (2019) MULTi x264.mkv"
    coldest.write_bytes(b"fake")

    repair = MagicMock()
    repair.find_possible_targets.return_value = [(coldest, 50.0)]

    movie = Movie(
        title="Ukryta gra",
        original_title="Ukryta gra",
        year=2019,
        genres=("Drame",),
        duration_seconds=5760,  # 96 min
        tmdb_id=585759,
    )

    # Sans titre alternatif : le fichier ne matche pas → rejeté
    finder_no_alt = MovieFileFinder(
        video_dir=video_dir,
        repair_service=repair,
        parser=parser,
        media_info_extractor=_extractor(5760),
    )
    assert finder_no_alt.find(movie) is None

    # Avec le titre AKA « The Coldest Game » → trouvé et accepté
    finder = MovieFileFinder(
        video_dir=video_dir,
        repair_service=repair,
        parser=parser,
        media_info_extractor=_extractor(5760),
        alt_title_provider=lambda m: ["The Coldest Game"],
    )
    found = finder.find(movie)
    assert found is not None
    assert found.storage_path == coldest

    # La recherche storage a bien été lancée avec le titre alternatif
    queried = [
        str(call.args[0]) for call in repair.find_possible_targets.call_args_list
    ]
    assert any("The Coldest Game" in q for q in queried)


def test_search_manual_returns_title_ranked_candidates_without_guards(
    video_dir, storage_dir, parser
):
    """Recherche manuelle : classe par similarité de titre, sans garde année/durée.

    Cas Irréversible (recut 2023) : l'utilisateur tape un titre et valide à l'œil
    (+ mpv). On renvoie tous les candidats, même ceux qui échoueraient au seuil 85.
    """
    integrale = (
        storage_dir
        / "Films"
        / "Drame"
        / "Irréversible, Inversion intégrale (2023) MULTi HEVC 1080p.mkv"
    )
    integrale.write_bytes(b"fake")
    other = storage_dir / "Films" / "Drame" / "Autre Film (2010) x264.mkv"
    other.write_bytes(b"fake")

    repair = MagicMock()
    repair.find_possible_targets.return_value = [(integrale, 65.0), (other, 40.0)]

    finder = MovieFileFinder(
        video_dir=video_dir,
        repair_service=repair,
        parser=parser,
        media_info_extractor=_extractor(8000),
    )

    results = finder.search_manual("Inversion intégrale", year=2002, limit=10)

    # Tous les candidats remontent (aucun filtrage par seuil), triés par score
    assert [c.storage_path for c in results] == [integrale, other]
    assert results[0].media_info is not None  # durée dispo pour l'affichage

    # La recherche a utilisé le titre saisi
    queried = [
        str(call.args[0]) for call in repair.find_possible_targets.call_args_list
    ]
    assert any("Inversion intégrale" in q for q in queried)


def test_tier1_broken_symlink_falls_back_to_tier2(video_dir, storage_dir, parser):
    """Tier 1 : symlink cassé → bascule tier 2 (durée concordante → accepté)."""
    missing = storage_dir / "Films" / "Drame" / "Cube (1997) x264.mkv"
    link = video_dir / "Films" / "Drame" / "Cube (1997) x264.mkv"
    link.symlink_to(missing)  # cible inexistante

    real = storage_dir / "Films" / "Drame" / "cube.1997.bluray.x264.mkv"
    real.write_bytes(b"fake")

    repair = MagicMock()
    repair.find_possible_targets.return_value = [(real, 90.0)]
    finder = MovieFileFinder(
        video_dir=video_dir,
        repair_service=repair,
        parser=parser,
        media_info_extractor=_extractor(5600),
    )

    movie = Movie(title="Cube", year=1997, genres=("Drame",), duration_seconds=5580)
    found = finder.find(movie)

    assert found is not None
    assert found.existing_symlink is None
    assert found.storage_path == real
