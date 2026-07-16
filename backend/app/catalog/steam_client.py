from dataclasses import dataclass

import httpx


@dataclass
class FetchedGame:
    steam_app_id: int
    title: str
    regular_price: int
    currency: str
    header_image_url: str | None


class SteamFetchError(Exception):
    pass


def fetch_game(appid: int, *, cc: str = "us", client: httpx.Client | None = None) -> FetchedGame:
    owns_client = client is None
    client = client or httpx.Client(timeout=10.0)
    try:
        response = client.get(
            "https://store.steampowered.com/api/appdetails",
            params={"appids": appid, "cc": cc, "l": "en"},
        )
        response.raise_for_status()
        payload = response.json()
    finally:
        if owns_client:
            client.close()

    entry = payload.get(str(appid))
    if entry is None or not entry.get("success"):
        raise SteamFetchError(f"appdetails lookup failed for appid={appid}")

    data = entry["data"]
    if data.get("is_free"):
        raise SteamFetchError(f"appid={appid} is free; no MSRP to catalog")

    price_overview = data.get("price_overview")
    if not price_overview:
        raise SteamFetchError(f"appid={appid} has no price_overview (unreleased/region-locked)")

    return FetchedGame(
        steam_app_id=appid,
        title=data["name"],
        regular_price=price_overview["initial"],
        currency=price_overview["currency"],
        header_image_url=data.get("header_image"),
    )
