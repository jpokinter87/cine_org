"""Tests : garde-fou anti-homonyme par année au matching des séries.

Le scoring séries est à 100 % titre : deux séries homonymes d'époques
différentes sortent toutes deux à 100 %, l'ambiguïté bloque l'auto-validation
et expose l'utilisateur à un mauvais rattachement.

Cas réel : « Miracle Workers » existe en 2006 (5 épisodes en saison 1) et en
2019 (7 épisodes). Les fichiers `Miracle.Workers.2019.S01E01..E05` gardaient
les deux candidats, seuls E06 et E07 étaient départagés par le comptage
d'épisodes.

Principe retenu : on n'écarte que ce qu'on identifie **formellement** comme
divergent, et seulement s'il reste au moins un candidat aligné.
"""

from __future__ import annotations

from src.core.ports.api_clients import SearchResult
from src.services.workflow.pending_factory import filter_by_year


def _candidate(cid: str, year: int | None) -> SearchResult:
    return SearchResult(
        id=cid, title="Miracle Workers", year=year, score=100.0, source="tvdb"
    )


def test_ecarte_homonyme_dont_annee_diverge():
    """Cas Miracle Workers : le show de 2006 est écarté pour un fichier 2019."""
    candidates = [_candidate("342818", 2019), _candidate("79254", 2006)]

    result = filter_by_year(candidates, 2019)

    assert [c.id for c in result] == ["342818"]


def test_tolerance_d_un_an():
    """Un écart d'un an reste aligné (année de diffusion vs année de release)."""
    candidates = [_candidate("1", 2018), _candidate("2", 2020), _candidate("3", 2015)]

    result = filter_by_year(candidates, 2019)

    assert [c.id for c in result] == ["1", "2"]


def test_conserve_tout_si_aucun_candidat_aligne():
    """Année du nom de fichier fausse → on garde tout, arbitrage à l'utilisateur."""
    candidates = [_candidate("79254", 2006), _candidate("999", 2001)]

    result = filter_by_year(candidates, 2019)

    assert result == candidates


def test_annee_absente_liste_inchangee():
    """Sans année parsée, aucun filtrage possible."""
    candidates = [_candidate("342818", 2019), _candidate("79254", 2006)]

    assert filter_by_year(candidates, None) == candidates


def test_conserve_candidat_sans_annee():
    """Année inconnue ≠ année divergente : le candidat est conservé."""
    candidates = [_candidate("342818", 2019), _candidate("42", None)]

    result = filter_by_year(candidates, 2019)

    assert [c.id for c in result] == ["342818", "42"]


def test_liste_vide():
    assert filter_by_year([], 2019) == []
