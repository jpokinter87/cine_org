"""Tests de la detection de decalage de saison (cours d'anime).

Les teams livrent les arcs d'anime en cours numerotes S01/S02/S03 alors que
le fournisseur les range dans une seule saison a numerotation continue
(Bleach TYBW = saison 17, episodes 1 a 50). Ce module detecte le decalage et
propose le realignement, sans jamais l'appliquer seul.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.ports.api_clients import EpisodeDetails
from src.services.season_remap import detect_season_remap

SEASON_NAMES = {
    1: ("死神代行篇",),
    17: ("千年血戦篇", "Bleach: Thousand-Year Blood War"),
}

# Les 4 cours de la saison 17 : 13 + 13 + 14 episodes diffuses, puis 10 en cours.
_COURS = [
    (1, 13, "2022-10-11", "2022-12-27"),
    (14, 26, "2023-07-08", "2023-09-30"),
    (27, 40, "2024-10-05", "2024-12-28"),
    (41, 50, "2026-07-25", "2026-09-26"),
]


def _season_17_episodes() -> list[EpisodeDetails]:
    """Saison 17 avec des dates realistes : cours separes par > 6 mois."""
    episodes = []
    for start, end, first_air, _ in _COURS:
        year, month, _ = first_air.split("-")
        for offset, number in enumerate(range(start, end + 1)):
            day = 1 + offset
            episodes.append(
                EpisodeDetails(
                    id=str(number),
                    title=f"Episode {number}",
                    season_number=17,
                    episode_number=number,
                    air_date=f"{year}-{month}-{day:02d}",
                )
            )
    return episodes


def _client(season_names=None, episodes=None) -> MagicMock:
    client = MagicMock()
    client.get_season_names = AsyncMock(
        return_value=SEASON_NAMES if season_names is None else season_names
    )
    client.get_all_episodes = AsyncMock(
        return_value=_season_17_episodes() if episodes is None else episodes
    )
    return client


@pytest.mark.asyncio
async def test_cour_2_est_realigne_sur_la_numerotation_continue() -> None:
    """S02E05 d'un arc devient S17E18 (13 episodes de cour 1 en amont)."""
    remap = await detect_season_remap(
        _client(),
        series_id="74796",
        series_title="BLEACH",
        filename="BLEACH.Thousand-Year.Blood.War.S02E05.MULTi.1080p.WEB.H264-TFA.mkv",
        season=2,
        episode=5,
    )

    assert remap is not None
    assert (remap.target_season, remap.target_episode) == (17, 18)
    assert remap.cour == 2
    assert remap.season_name == "Bleach: Thousand-Year Blood War"


@pytest.mark.asyncio
async def test_premier_cour_conserve_la_numerotation() -> None:
    """Le cour 1 garde ses numeros mais change de saison."""
    remap = await detect_season_remap(
        _client(),
        series_id="74796",
        series_title="BLEACH",
        filename="BLEACH.Thousand-Year.Blood.War.S01E01.MULTi.1080p.WEB.H264-TFA.mkv",
        season=1,
        episode=1,
    )

    assert remap is not None
    assert (remap.target_season, remap.target_episode) == (17, 1)


@pytest.mark.asyncio
async def test_troisieme_cour() -> None:
    """S03E14 devient S17E40 (13 + 13 episodes en amont)."""
    remap = await detect_season_remap(
        _client(),
        series_id="74796",
        series_title="BLEACH",
        filename="BLEACH.Thousand-Year.Blood.War.S03E14.FiNAL.MULTi.1080p.mkv",
        season=3,
        episode=14,
    )

    assert remap is not None
    assert (remap.target_season, remap.target_episode) == (17, 40)


@pytest.mark.asyncio
async def test_sans_titre_parasite_aucun_appel_api() -> None:
    """Un nom de fichier sans tokens en trop n'interroge meme pas TVDB."""
    client = _client()

    remap = await detect_season_remap(
        client,
        series_id="81189",
        series_title="Breaking Bad",
        filename="Breaking.Bad.S01E01.MULTi.1080p.mkv",
        season=1,
        episode=1,
    )

    assert remap is None
    client.get_season_names.assert_not_awaited()


@pytest.mark.asyncio
async def test_aucun_nom_de_saison_ne_correspond() -> None:
    """Des tokens en trop qui ne matchent aucune saison ne declenchent rien."""
    remap = await detect_season_remap(
        _client(season_names={1: ("Arc introductif",)}),
        series_id="74796",
        series_title="BLEACH",
        filename="BLEACH.Thousand-Year.Blood.War.S01E01.MULTi.1080p.mkv",
        season=1,
        episode=1,
    )

    assert remap is None


@pytest.mark.asyncio
async def test_saison_deja_correcte_ne_propose_rien() -> None:
    """Un fichier deja nomme S17E18 n'a rien a realigner."""
    remap = await detect_season_remap(
        _client(),
        series_id="74796",
        series_title="BLEACH",
        filename="BLEACH.Thousand-Year.Blood.War.S17E18.MULTi.1080p.mkv",
        season=17,
        episode=18,
    )

    assert remap is None


@pytest.mark.asyncio
async def test_cour_inexistant_ne_propose_rien() -> None:
    """Un cour au-dela de ceux publies est laisse a la validation manuelle."""
    remap = await detect_season_remap(
        _client(),
        series_id="74796",
        series_title="BLEACH",
        filename="BLEACH.Thousand-Year.Blood.War.S09E01.MULTi.1080p.mkv",
        season=9,
        episode=1,
    )

    assert remap is None


@pytest.mark.asyncio
async def test_episode_hors_du_cour_ne_propose_rien() -> None:
    """Un numero d'episode au-dela du cour detecte reste non resolu."""
    remap = await detect_season_remap(
        _client(),
        series_id="74796",
        series_title="BLEACH",
        filename="BLEACH.Thousand-Year.Blood.War.S01E20.MULTi.1080p.mkv",
        season=1,
        episode=20,
    )

    assert remap is None


@pytest.mark.asyncio
async def test_saison_sans_dates_de_diffusion_ne_propose_rien() -> None:
    """Sans dates, le decoupage en cours est impossible."""
    episodes = [
        EpisodeDetails(
            id=str(n), title="x", season_number=17, episode_number=n, air_date=None
        )
        for n in range(1, 51)
    ]

    remap = await detect_season_remap(
        _client(episodes=episodes),
        series_id="74796",
        series_title="BLEACH",
        filename="BLEACH.Thousand-Year.Blood.War.S02E05.MULTi.1080p.mkv",
        season=2,
        episode=5,
    )

    assert remap is None


@pytest.mark.asyncio
async def test_panne_api_ne_remonte_pas() -> None:
    """Une erreur TVDB laisse le fichier en validation manuelle, sans exception."""
    client = _client()
    client.get_season_names = AsyncMock(side_effect=RuntimeError("TVDB down"))

    remap = await detect_season_remap(
        client,
        series_id="74796",
        series_title="BLEACH",
        filename="BLEACH.Thousand-Year.Blood.War.S02E05.MULTi.1080p.mkv",
        season=2,
        episode=5,
    )

    assert remap is None


@pytest.mark.asyncio
async def test_client_absent_ne_propose_rien() -> None:
    """Sans client TVDB la detection est inactive."""
    assert (
        await detect_season_remap(
            None,
            series_id="74796",
            series_title="BLEACH",
            filename="BLEACH.Thousand-Year.Blood.War.S02E05.mkv",
            season=2,
            episode=5,
        )
        is None
    )


@pytest.mark.asyncio
async def test_label_resume_le_realignement() -> None:
    """Le libelle affiche a l'utilisateur nomme l'arc, le cour et la cible."""
    remap = await detect_season_remap(
        _client(),
        series_id="74796",
        series_title="BLEACH",
        filename="BLEACH.Thousand-Year.Blood.War.S02E05.MULTi.1080p.mkv",
        season=2,
        episode=5,
    )

    assert remap.label == (
        "cour 2 de « Bleach: Thousand-Year Blood War » → S17E18 (au lieu de S02E05)"
    )
