from typing import Any, Dict

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cache import cache
from config import settings
from history import add_event, latest_events
from market import load_market_prices
from okx_client import OKXClient
from portfolio import build_portfolio
from recommendation import build_recommendation
from utils import iso_ts

app = FastAPI(title="CryptoPilot Backend", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)

@app.get("/")
async def root() -> Dict[str, Any]:
    return {"ok": True, "service": "CryptoPilot Backend", "version": "2.0.0", "endpoints": ["/api/health", "/api/summary", "/api/history"]}

@app.get("/api/health")
async def health() -> Dict[str, Any]:
    return {"ok": True, "service": "CryptoPilot Backend", "version": "2.0.0", "updatedAt": iso_ts()}

@app.get("/api/summary")
async def summary() -> Dict[str, Any]:
    cached = cache.get("summary")
    if cached:
        return cached
    warnings: list[str] = []
    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        prices = await load_market_prices(client)
        okx = OKXClient(client)
        raw, okx_warnings = await okx.load_raw_sources()
        warnings.extend(okx_warnings)
        portfolio = build_portfolio(raw, prices)
        recommendation = build_recommendation(portfolio)
        eth_asset = next((a for a in portfolio["assets"] if a["sym"] == "ETH"), {})
        response: Dict[str, Any] = {
            "ok": True,
            "source": "OKX",
            "service": "CryptoPilot Backend",
            "version": "2.0.0",
            "ethPrice": prices.get("ETH", 0.0),
            "ethQty": portfolio.get("ethQty", 0.0),
            "ethAvg": eth_asset.get("avg", 0.0),
            "availableUsdt": portfolio.get("availableUsdt", 0.0),
            "tradingUsdt": portfolio.get("tradingUsdt", 0.0),
            "fundingUsdt": portfolio.get("fundingUsdt", 0.0),
            "cappedCapital": portfolio.get("cappedCapital", 0.0),
            "estimatedTotalUsd": portfolio.get("estimatedTotalUsd", 0.0),
            "tradingTotalUsd": portfolio.get("tradingTotalUsd", 0.0),
            "fundingTotalUsd": portfolio.get("fundingTotalUsd", 0.0),
            "assets": portfolio.get("assets", []),
            "portfolio": portfolio,
            "recommendation": recommendation,
            "warnings": warnings,
            "updatedAt": iso_ts(),
        }
        add_event({
            "updatedAt": response["updatedAt"],
            "ethPrice": response["ethPrice"],
            "availableUsdt": response["availableUsdt"],
            "estimatedTotalUsd": response["estimatedTotalUsd"],
            "decision": recommendation["decision"],
            "confidence": recommendation["confidence"],
            "warnings": warnings,
        })
        cache.set("summary", response, settings.cache_ttl_seconds)
        return response

@app.get("/api/history")
async def history() -> Dict[str, Any]:
    return {"ok": True, "service": "CryptoPilot Backend", "version": "2.0.0", "items": latest_events(), "updatedAt": iso_ts()}
