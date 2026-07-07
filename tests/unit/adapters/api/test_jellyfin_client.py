import httpx
import pytest
import respx

from src.adapters.api.jellyfin_client import JellyfinClient

BASE = "http://jf:8096"
VFOLDERS = [
    {"Name": "Partage Films", "ItemId": "film-id", "CollectionType": "movies"},
    {"Name": "Partage Séries", "ItemId": "serie-id", "CollectionType": "tvshows"},
]


@pytest.mark.asyncio
@respx.mock
async def test_refresh_library_resolves_id_and_posts():
    respx.get(f"{BASE}/Library/VirtualFolders").mock(
        return_value=httpx.Response(200, json=VFOLDERS)
    )
    route = respx.post(f"{BASE}/Items/film-id/Refresh").mock(
        return_value=httpx.Response(204)
    )
    client = JellyfinClient(base_url=BASE, api_key="k")
    await client.refresh_library("Partage Films")
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_refresh_unknown_library_is_noop():
    respx.get(f"{BASE}/Library/VirtualFolders").mock(
        return_value=httpx.Response(200, json=VFOLDERS)
    )
    client = JellyfinClient(base_url=BASE, api_key="k")
    await client.refresh_library("Inexistante")  # ne lève pas


@pytest.mark.asyncio
@respx.mock
async def test_get_active_sessions_returns_list():
    respx.get(f"{BASE}/Sessions").mock(
        return_value=httpx.Response(
            200,
            json=[{"NowPlayingItem": {"Id": "x", "Path": "/media/.../Partage/Films/a.mkv"}}],
        )
    )
    client = JellyfinClient(base_url=BASE, api_key="k")
    sessions = await client.get_active_sessions()
    assert sessions[0]["NowPlayingItem"]["Path"].endswith("a.mkv")


@pytest.mark.asyncio
@respx.mock
async def test_auth_header_sent():
    route = respx.get(f"{BASE}/Sessions").mock(return_value=httpx.Response(200, json=[]))
    client = JellyfinClient(base_url=BASE, api_key="secret-token")
    await client.get_active_sessions()
    assert route.calls.last.request.headers["X-Emby-Token"] == "secret-token"
