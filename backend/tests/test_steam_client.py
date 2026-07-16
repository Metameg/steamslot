import httpx
import pytest

from app.catalog.steam_client import SteamFetchError, fetch_game


def _client_with_response(json_payload: dict, status_code: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=json_payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_game_parses_regular_price_not_discounted():
    payload = {
        "440": {
            "success": True,
            "data": {
                "name": "Team Fortress 2",
                "is_free": False,
                "price_overview": {"initial": 999, "final": 499, "currency": "USD"},
                "header_image": "https://example.com/tf2.jpg",
            },
        }
    }
    client = _client_with_response(payload)
    game = fetch_game(440, client=client)
    assert game.steam_app_id == 440
    assert game.title == "Team Fortress 2"
    assert game.regular_price == 999  # initial, NOT final/discounted
    assert game.currency == "USD"
    assert game.header_image_url == "https://example.com/tf2.jpg"


def test_fetch_game_raises_on_unsuccessful_lookup():
    client = _client_with_response({"999999": {"success": False}})
    with pytest.raises(SteamFetchError):
        fetch_game(999999, client=client)


def test_fetch_game_raises_on_free_game():
    payload = {"480": {"success": True, "data": {"name": "Spacewar", "is_free": True}}}
    client = _client_with_response(payload)
    with pytest.raises(SteamFetchError):
        fetch_game(480, client=client)


def test_fetch_game_raises_when_no_price_overview():
    payload = {"111": {"success": True, "data": {"name": "Unreleased Game", "is_free": False}}}
    client = _client_with_response(payload)
    with pytest.raises(SteamFetchError):
        fetch_game(111, client=client)
