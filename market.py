from typing import Dict

import httpx

from config import settings
from utils import safe_float


SYMBOLS: Dict[str, str] = {
    "ETH": "ETH-USDT",
    "XRP": "XRP-USDT",
    "SUI": "SUI-USDT",
    "BTC": "BTC-USDT",
    "SOL": "SOL-USDT",
    "BNB": "BNB-USDT",
}


async def public_ticker(client: httpx.AsyncClient, inst_id: str) -> float:
    response = await client.get(
        f"{settings.okx_base}/api/v5/market/ticker",
        params={"instId": inst_id},
    )
    response.raise_for_status()
    data = response.json()
    return safe_float(data.get("data", [{}])[0].get("last"))


async def load_market_prices(client: httpx.AsyncClient) -> Dict[str, float]:
    prices: Dict[str, float] = {}

    for sym, inst_id in SYMBOLS.items():
        try:
            prices[sym] = await public_ticker(client, inst_id)
        except Exception:
            prices[sym] = 0.0

    return prices
