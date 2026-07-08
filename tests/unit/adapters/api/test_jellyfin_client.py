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
async def test_scan_libraries_posts_library_refresh():
    # Le scan global (POST /Library/Refresh) est le SEUL déclencheur qui indexe
    # les fichiers fraîchement ajoutés ; le refresh ciblé /Items/{id}/Refresh ne
    # scanne pas le filesystem.
    route = respx.post(f"{BASE}/Library/Refresh").mock(return_value=httpx.Response(204))
    client = JellyfinClient(base_url=BASE, api_key="k")
    await client.scan_libraries()
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_library_item_count_resolves_id_and_returns_total():
    respx.get(f"{BASE}/Library/VirtualFolders").mock(
        return_value=httpx.Response(200, json=VFOLDERS)
    )
    route = respx.get(f"{BASE}/Items").mock(
        return_value=httpx.Response(200, json={"TotalRecordCount": 9, "Items": []})
    )
    client = JellyfinClient(base_url=BASE, api_key="k")
    count = await client.library_item_count("Partage Séries")
    assert count == 9
    assert route.calls.last.request.url.params["ParentId"] == "serie-id"


@pytest.mark.asyncio
@respx.mock
async def test_library_item_count_unknown_library_is_zero():
    respx.get(f"{BASE}/Library/VirtualFolders").mock(
        return_value=httpx.Response(200, json=VFOLDERS)
    )
    client = JellyfinClient(base_url=BASE, api_key="k")
    assert await client.library_item_count("Inexistante") == 0


@pytest.mark.asyncio
@respx.mock
async def test_get_active_sessions_returns_list():
    respx.get(f"{BASE}/Sessions").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "NowPlayingItem": {
                        "Id": "x",
                        "Path": "/media/.../Partage/Films/a.mkv",
                    }
                }
            ],
        )
    )
    client = JellyfinClient(base_url=BASE, api_key="k")
    sessions = await client.get_active_sessions()
    assert sessions[0]["NowPlayingItem"]["Path"].endswith("a.mkv")


@pytest.mark.asyncio
@respx.mock
async def test_auth_header_sent():
    route = respx.get(f"{BASE}/Sessions").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = JellyfinClient(base_url=BASE, api_key="secret-token")
    await client.get_active_sessions()
    assert route.calls.last.request.headers["X-Emby-Token"] == "secret-token"
