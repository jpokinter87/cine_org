"""Test câblage DI des composants du partage SP3b."""

from src.adapters.api.jellyfin_client import JellyfinClient
from src.adapters.funnel import FunnelController
from src.container import Container
from src.services.share.share_service import ShareService


def test_container_provides_share_components():
    container = Container()
    container.database.init()
    assert isinstance(container.jellyfin_client(), JellyfinClient)
    assert isinstance(container.funnel_controller(), FunnelController)
    assert isinstance(container.share_service(), ShareService)
