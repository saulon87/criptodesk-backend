from typing import Any, Dict, List

from config import settings
from market import SYMBOLS
from utils import safe_float

STABLES = {"USDT", "USDC", "USD"}

def _empty_balances() -> Dict[str, float]:
    return {sym: 0.0 for sym in SYMBOLS.keys()}

def _read_trading(raw: Dict[str, Any]) -> tuple[Dict[str, float], float, float]:
    balances = _empty_balances()
    usdt = 0.0
    total_usd = 0.0
    details = raw.get("trading", {}).get("data", [{}])[0].get("details", [])
    for item in details:
        ccy = item.get("ccy")
        cash_bal = safe_float(item.get("cashBal"))
        avail_bal = safe_float(item.get("availBal"))
        eq_usd = safe_float(item.get("eqUsd"))
        qty = cash_bal if cash_bal else avail_bal
        if ccy == "USDT":
            usdt += avail_bal if avail_bal else cash_bal
        if ccy in balances:
            balances[ccy] += qty
        total_usd += eq_usd
    return balances, usdt, total_usd

def _read_funding(raw: Dict[str, Any], prices: Dict[str, float]) -> tuple[Dict[str, float], float, float]:
    balances = _empty_balances()
    usdt = 0.0
    total_usd = 0.0
    details = raw.get("funding", {}).get("data", [])
    for item in details:
        ccy = item.get("ccy")
        bal = safe_float(item.get("bal"))
        avail_bal = safe_float(item.get("availBal"))
        avail_eq = safe_float(item.get("availEq"))
        qty = bal or avail_bal or avail_eq
        if ccy == "USDT":
            usdt += avail_bal or bal or avail_eq
        if ccy in balances:
            balances[ccy] += qty
        if ccy in STABLES:
            total_usd += qty
        elif ccy in prices:
            total_usd += qty * prices.get(ccy, 0.0)
    return balances, usdt, total_usd

def _read_asset_valuation(raw: Dict[str, Any]) -> float:
    data = raw.get("asset_valuation", {}).get("data", [])
    if not data:
        return 0.0
    first = data[0]
    for key in ("totalBal", "totalEq", "eq", "details"):
        value = first.get(key)
        if isinstance(value, (int, float, str)):
            amount = safe_float(value)
            if amount > 0:
                return amount
    return 0.0

def score_from_price(price: float, base: int) -> int:
    if not price:
        return base
    return max(0, min(100, 45 + round((price % 100) / 100 * 25)))

def build_portfolio(raw: Dict[str, Any], prices: Dict[str, float]) -> Dict[str, Any]:
    trading_balances, trading_usdt, trading_total_usd = _read_trading(raw)
    funding_balances, funding_usdt, funding_total_usd = _read_funding(raw, prices)
    valuation_total = _read_asset_valuation(raw)
    combined = {sym: trading_balances.get(sym, 0.0) + funding_balances.get(sym, 0.0) for sym in SYMBOLS}
    available_usdt = trading_usdt + funding_usdt
    capped_capital = min(available_usdt, settings.max_operating_capital)
    calculated_total = trading_total_usd + funding_total_usd
    estimated_total_usd = valuation_total if valuation_total > 0 else calculated_total
    base_scores = {"ETH": 57, "XRP": 53, "SUI": 50, "BTC": 49, "SOL": 49, "BNB": 48}
    ordered_symbols = ["ETH"] + [s for s in SYMBOLS.keys() if s != "ETH"]
    assets: List[Dict[str, Any]] = []
    for sym in ordered_symbols:
        price = prices.get(sym, 0.0)
        qty = combined.get(sym, 0.0)
        value = qty * price
        allocation = (value / estimated_total_usd * 100) if estimated_total_usd else 0.0
        assets.append({
            "sym": sym,
            "qty": qty,
            "tradingQty": trading_balances.get(sym, 0.0),
            "fundingQty": funding_balances.get(sym, 0.0),
            "price": price,
            "value": value,
            "allocationPct": allocation,
            "avg": 0.0,
            "score": score_from_price(price, base_scores.get(sym, 50)),
        })
    return {
        "availableUsdt": available_usdt,
        "tradingUsdt": trading_usdt,
        "fundingUsdt": funding_usdt,
        "cappedCapital": capped_capital,
        "estimatedTotalUsd": estimated_total_usd,
        "calculatedTotalUsd": calculated_total,
        "assetValuationTotalUsd": valuation_total,
        "tradingTotalUsd": trading_total_usd,
        "fundingTotalUsd": funding_total_usd,
        "assets": assets,
        "ethQty": combined.get("ETH", 0.0),
    }
