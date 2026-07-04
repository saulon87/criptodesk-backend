import os
import hmac
import base64
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

OKX_BASE = "https://www.okx.com"
MAX_CAPITAL = 9.44

app = FastAPI(title="CriptoDesk OKX Backend", version="1.1.0")

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

STABLES = {"USDT", "USDC", "USD"}


def iso_ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


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
        hmac.new(
            secret_key.encode("utf-8"),
            prehash.encode("utf-8"),
            hashlib.sha256,
        ).digest()
    ).decode("utf-8")

    return {
        "OK-ACCESS-KEY": api_key,
        "OK-ACCESS-SIGN": signature,
        "OK-ACCESS-TIMESTAMP": timestamp,
        "OK-ACCESS-PASSPHRASE": passphrase,
        "Content-Type": "application/json",
        "x-simulated-trading": "0",
    }


async def okx_get(client: httpx.AsyncClient, path: str) -> Dict[str, Any]:
    headers = okx_headers("GET", path, "")
    response = await client.get(f"{OKX_BASE}{path}", headers=headers)
    response.raise_for_status()
    return response.json()


async def public_ticker(client: httpx.AsyncClient, inst_id: str) -> float:
    response = await client.get(
        f"{OKX_BASE}/api/v5/market/ticker",
        params={"instId": inst_id},
    )
    response.raise_for_status()
    data = response.json()
    return safe_float(data.get("data", [{}])[0].get("last"))


def score_from_price(price: float, base: int) -> int:
    if not price:
        return base
    return max(0, min(100, 45 + round((price % 100) / 100 * 25)))


@app.get("/")
async def root() -> Dict[str, Any]:
    return {
        "ok": True,
        "service": "CriptoDesk OKX Backend",
        "version": "1.1.0",
        "endpoints": ["/api/health", "/api/summary"],
    }


@app.get("/api/health")
async def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "service": "CriptoDesk OKX Backend",
        "version": "1.1.0",
        "updatedAt": iso_ts(),
    }


@app.get("/api/summary")
async def summary() -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        prices: Dict[str, float] = {}

        for sym, inst_id in SYMBOLS.items():
            try:
                prices[sym] = await public_ticker(client, inst_id)
            except Exception:
                prices[sym] = 0.0

        trading_balances: Dict[str, float] = {sym: 0.0 for sym in SYMBOLS}
        funding_balances: Dict[str, float] = {sym: 0.0 for sym in SYMBOLS}

        trading_usdt = 0.0
        funding_usdt = 0.0
        trading_total_usd = 0.0
        funding_total_usd = 0.0
        warnings: List[str] = []

        try:
            account = await okx_get(client, "/api/v5/account/balance")
            account_data = account.get("data", [])

            if account_data:
                details = account_data[0].get("details", [])

                for item in details:
                    ccy = item.get("ccy")
                    cash_bal = safe_float(item.get("cashBal"))
                    avail_bal = safe_float(item.get("availBal"))
                    eq_usd = safe_float(item.get("eqUsd"))

                    qty = cash_bal if cash_bal else avail_bal

                    if ccy == "USDT":
                        trading_usdt = avail_bal if avail_bal else cash_bal

                    if ccy in trading_balances:
                        trading_balances[ccy] = qty

                    trading_total_usd += eq_usd

        except Exception as exc:
            warnings.append(f"No se pudo leer Trading: {str(exc)}")

        try:
            asset = await okx_get(client, "/api/v5/asset/balances")
            details = asset.get("data", [])

            for item in details:
                ccy = item.get("ccy")
                bal = safe_float(item.get("bal"))
                avail_bal = safe_float(item.get("availBal"))
                avail_eq = safe_float(item.get("availEq"))

                qty = bal or avail_bal or avail_eq

                if ccy == "USDT":
                    funding_usdt = avail_bal or bal or avail_eq

                if ccy in funding_balances:
                    funding_balances[ccy] = qty

                if ccy in STABLES:
                    funding_total_usd += qty
                elif ccy in SYMBOLS:
                    funding_total_usd += qty * prices.get(ccy, 0.0)

        except Exception as exc:
            warnings.append(f"No se pudo leer Funding/Fondos: {str(exc)}")

        combined_balances: Dict[str, float] = {}
        for sym in SYMBOLS:
            combined_balances[sym] = trading_balances.get(sym, 0.0) + funding_balances.get(sym, 0.0)

        available_usdt = trading_usdt + funding_usdt
        capped_capital = min(available_usdt, MAX_CAPITAL)
        estimated_total_usd = trading_total_usd + funding_total_usd

        base_scores = {
            "ETH": 57,
            "XRP": 53,
            "SUI": 50,
            "BTC": 49,
            "SOL": 49,
            "BNB": 48,
        }

        assets: List[Dict[str, Any]] = []
        for sym in SYMBOLS:
            price = prices.get(sym, 0.0)
            qty = combined_balances.get(sym, 0.0)
            assets.append(
                {
                    "sym": sym,
                    "qty": qty,
                    "tradingQty": trading_balances.get(sym, 0.0),
                    "fundingQty": funding_balances.get(sym, 0.0),
                    "price": price,
                    "value": qty * price,
                    "avg": 0.0,
                    "score": score_from_price(price, base_scores.get(sym, 50)),
                }
            )

        return {
            "ok": len(warnings) < 2,
            "source": "OKX",
            "version": "1.1.0",
            "ethPrice": prices.get("ETH", 0.0),
            "ethQty": combined_balances.get("ETH", 0.0),
            "ethAvg": 0.0,
            "availableUsdt": available_usdt,
            "tradingUsdt": trading_usdt,
            "fundingUsdt": funding_usdt,
            "cappedCapital": capped_capital,
            "estimatedTotalUsd": estimated_total_usd,
            "tradingTotalUsd": trading_total_usd,
            "fundingTotalUsd": funding_total_usd,
            "assets": assets,
            "warnings": warnings,
            "updatedAt": iso_ts(),
        }
