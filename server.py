import os
import time
import hmac
import base64
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

OKX_BASE = "https://www.okx.com"
MAX_CAPITAL = 9.44

app = FastAPI(title="CriptoDesk OKX Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)

SYMBOLS = {
    "ETH": "ETH-USDT",
    "XRP": "XRP-USDT",
    "SUI": "SUI-USDT",
    "BTC": "BTC-USDT",
    "SOL": "SOL-USDT",
    "BNB": "BNB-USDT",
}

def iso_ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

def env_required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Falta variable de entorno: {name}")
    return value

def okx_headers(method: str, path: str, body: str = "") -> Dict[str, str]:
    api_key = env_required("OKX_API_KEY")
    secret_key = env_required("OKX_SECRET_KEY")
    passphrase = env_required("OKX_PASSPHRASE")

    timestamp = iso_ts()
    prehash = f"{timestamp}{method.upper()}{path}{body}"
    signature = base64.b64encode(
        hmac.new(secret_key.encode("utf-8"), prehash.encode("utf-8"), hashlib.sha256).digest()
    ).decode("utf-8")

    return {
        "OK-ACCESS-KEY": api_key,
        "OK-ACCESS-SIGN": signature,
        "OK-ACCESS-TIMESTAMP": timestamp,
        "OK-ACCESS-PASSPHRASE": passphrase,
        "Content-Type": "application/json",
        "x-simulated-trading": "0",
    }

async def public_ticker(client: httpx.AsyncClient, inst_id: str) -> float:
    r = await client.get(f"{OKX_BASE}/api/v5/market/ticker", params={"instId": inst_id})
    r.raise_for_status()
    data = r.json()
    return float(data["data"][0]["last"])

async def okx_get(client: httpx.AsyncClient, path: str) -> Dict[str, Any]:
    headers = okx_headers("GET", path, "")
    r = await client.get(f"{OKX_BASE}{path}", headers=headers)
    r.raise_for_status()
    return r.json()

def score_from_price(price: float, base: int) -> int:
    # Score simple y estable, compatible con la lógica visual actual.
    if not price:
        return base
    return max(0, min(100, 45 + round((price % 100) / 100 * 25)))

@app.get("/")
async def root() -> Dict[str, Any]:
    return {"ok": True, "service": "CriptoDesk OKX Backend", "endpoints": ["/api/health", "/api/summary"]}

@app.get("/api/health")
async def health() -> Dict[str, Any]:
    return {"ok": True, "service": "CriptoDesk OKX Backend", "updatedAt": iso_ts()}

@app.get("/api/summary")
async def summary() -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=12.0) as client:
        prices: Dict[str, float] = {}
        for sym, inst in SYMBOLS.items():
            try:
                prices[sym] = await public_ticker(client, inst)
            except Exception:
                prices[sym] = 0.0

        available_usdt: Optional[float] = None
        balances: Dict[str, float] = {sym: 0.0 for sym in SYMBOLS.keys()}

        try:
            account = await okx_get(client, "/api/v5/account/balance")
            details = account.get("data", [{}])[0].get("details", [])
            for item in details:
                ccy = item.get("ccy")
                qty = float(item.get("cashBal") or item.get("availBal") or 0)
                if ccy == "USDT":
                    available_usdt = float(item.get("availBal") or item.get("cashBal") or 0)
                if ccy in balances:
                    balances[ccy] = qty
        except Exception as exc:
            return {
                "ok": False,
                "error": f"No fue posible leer OKX: {str(exc)}",
                "ethPrice": prices.get("ETH", 0.0),
                "updatedAt": iso_ts(),
            }

        assets: List[Dict[str, Any]] = []
        base_scores = {"ETH": 57, "XRP": 53, "SUI": 50, "BTC": 49, "SOL": 49, "BNB": 48}
        for sym in SYMBOLS.keys():
            price = prices.get(sym, 0.0)
            qty = balances.get(sym, 0.0)
            assets.append({
                "sym": sym,
                "qty": qty,
                "price": price,
                "value": qty * price,
                "avg": 0.0,
                "score": score_from_price(price, base_scores.get(sym, 50)),
            })

        capped = min(available_usdt or 0.0, MAX_CAPITAL)

        return {
            "ok": True,
            "source": "OKX",
            "ethPrice": prices.get("ETH", 0.0),
            "ethQty": balances.get("ETH", 0.0),
            "ethAvg": 0.0,
            "availableUsdt": available_usdt or 0.0,
            "cappedCapital": capped,
            "assets": assets,
            "updatedAt": iso_ts(),
        }
