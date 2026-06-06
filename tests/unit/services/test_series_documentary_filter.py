"""Tests : exclusion stricte des séries documentaires au matching.

Le répertoire de téléchargement ``temp/Séries`` ne contient jamais de
séries documentaires. Un candidat dont les genres incluent
« Documentary » (TVDB, anglais) ou « Documentaire » (TMDB, français) ne
peut donc pas être le bon résultat et doit être écarté des candidats.

En cas d'erreur API ou d'absence de genres, le candidat est conservé par
précaution (on n'exclut que ce qu'on identifie formellement).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.core.ports.api_clients import MediaDetails, SearchResult
from src.services.workflow.pending_factory import filter_documentary_series


def _details(genres: list[str]) -> MediaDetails:
    return MediaDetails(id="x", title="t", genres=tuple(genres))


def _candidate(cid: str, title: str) -> SearchResult:
    return SearchResult(id=cid, title=title, year=2026, score=90.0, source="tvdb")


@pytest.mark.asyncio
async def test_exclut_candidat_documentaire_genre_anglais():
    """Un candidat TVDB avec genre « Documentary » est écarté."""
    details_by_id = {
        "1": _details(["Drama", "Mini-Series"]),
        "2": _details(["Documentary"]),
    }
    client = AsyncMock()
    client.get_details = AsyncMock(side_effect=lambda cid: details_by_id[cid])

    candidates = [_candidate("1", "Sous ses yeux"), _candidate("2", "Il Testimonio")]
    result = await filter_documentary_series(client, candidates)

    assert [c.id for c in result] == ["1"]


@pytest.mark.asyncio
async def test_exclut_documentaire_genre_francais():
    """Le genre français « Documentaire » est aussi reconnu."""
    client = AsyncMock()
    client.get_details = AsyncMock(return_value=_details(["Documentaire"]))

    result = await filter_documentary_series(client, [_candidate("9", "Doc")])

    assert result == []


@pytest.mark.asyncio
async def test_conserve_candidat_si_get_details_echoue():
    """Erreur API → on garde le candidat (on n'exclut que le formellement doc)."""
    client = AsyncMock()
    client.get_details = AsyncMock(side_effect=RuntimeError("API down"))

    candidates = [_candidate("1", "Série classique")]
    result = await filter_documentary_series(client, candidates)

    assert [c.id for c in result] == ["1"]


@pytest.mark.asyncio
async def test_client_none_retourne_candidats_inchanges():
    candidates = [_candidate("1", "Série")]
    assert await filter_documentary_series(None, candidates) == candidates
