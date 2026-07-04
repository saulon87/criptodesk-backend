from typing import Any, Dict, List, Tuple

from config import settings
from market import SYMBOLS
from utils import first_positive, round_money, safe_float


STABLES = {"USDT", "USDC", "USD"}

BALANCE_KEYS = (
    "cashBal",
    "availBal",
    "bal",
    "availEq",
    "eq",
    "totalBal",
    "amt",
    "amount",
    "availAmt",
    "holding",
    "quantity",
    "qty",
)

USD_KEYS = (
    "eqUsd",
    "usd",
    "usdValue",
    "valueUsd",
    "totalEq",
    "totalBal",
)


def _normalize_ccy(value: Any) -> str:
    return str(value or "").upper().strip()


def _extract_qty(item: Dict[str, Any]) -> float:
    return first_positive(*(item.get(k) for k in BALANCE_KEYS))


def _extract_usd_value(item: Dict[str, Any]) -> float:
    return first_positive(*(item.get(k) for k in USD_KEYS))


def _walk_items(node: Any) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []

    if isinstance(node, dict):
        if any(k in node for k in ("ccy", "currency", "coin", "token")):
            found.append(node)

        for value in node.values():
            found.extend(_walk_items(value))

    elif isinstance(node, list):
        for value in node:
            found.extend(_walk_items(value))

    return found


def _collect_balances_from_source(
    payload: Dict[str, Any],
    prices: Dict[str, float],
) -> Tuple[Dict[str, Dict[str, float]], float, float]:
    balances: Dict[str, Dict[str, float]] = {}
    available_usdt = 0.0

    for item in _walk_items(payload):
        ccy = _normalize_ccy(
            item.get("ccy")
            or item.get("currency")
            or item.get("coin")
            or item.get("token")
        )

        if not ccy:
            continue

        qty = _extract_qty(item)
        usd_value = _extract_usd_value(item)

        if qty <= 0 and usd_value <= 0:
            continue

        if ccy not in balances:
            balances[ccy] = {"qty": 0.0, "value": 0.0, "available": 0.0}

        if qty > 0:
            balances[ccy]["qty"] += qty

        if usd_value > 0 and ccy not in STABLES:
            balances[ccy]["value"] += usd_value
        elif ccy in STABLES:
            balances[ccy]["value"] += qty
        elif ccy in prices:
            balances[ccy]["value"] += qty * prices.get(ccy, 0.0)

        if ccy == "USDT":
            available = first_positive(
                item.get("availBal"),
                item.get("bal"),
                item.get("cashBal"),
                item.get("availEq"),
                item.get("qty"),
            )
            available_usdt += available
            balances[ccy]["available"] += available

    total_usd = sum(data.get("value", 0.0) for data in balances.values())
    return balances, available_usdt, total_usd


def _read_asset_valuation(raw: Dict[str, Any]) -> float:
    data = raw.get("asset_valuation", {}).get("data", [])
    if not data:
        return 0.0

    first = data[0]

    for key in ("totalBal", "totalEq", "eq"):
        amount = safe_float(first.get(key))
        if amount > 0:
            return amount

    details = first.get("details")
    if isinstance(details, dict):
        total = sum(safe_float(value) for value in details.values())
        if total > 0:
            return total

    return 0.0


def _merge_source(
    target: Dict[str, Dict[str, Any]],
    source_name: str,
    source_data: Dict[str, Dict[str, float]],
) -> None:
    for ccy, data in source_data.items():
        if ccy not in target:
            target[ccy] = {"qty": 0.0, "value": 0.0, "available": 0.0, "sources": {}}

        target[ccy]["qty"] += data.get("qty", 0.0)
        target[ccy]["value"] += data.get("value", 0.0)
        target[ccy]["available"] += data.get("available", 0.0)
        target[ccy]["sources"][source_name] = {
            "qty": data.get("qty", 0.0),
            "value": data.get("value", 0.0),
            "available": data.get("available", 0.0),
        }


def score_from_price(price: float, base: int) -> int:
    if not price:
        return base

    return max(0, min(100, 45 + round((price % 100) / 100 * 25)))


def _asset_object(
    sym: str,
    data: Dict[str, Any],
    price: float,
    estimated_total_usd: float,
    score: int,
) -> Dict[str, Any]:
    qty = data.get("qty", 0.0)
    value = data.get("value", 0.0)

    if value <= 0 and qty > 0 and price > 0:
        value = qty * price

    allocation = (value / estimated_total_usd * 100) if estimated_total_usd else 0.0

    return {
        "sym": sym,
        "qty": round_money(qty, 10),
        "price": round_money(price, 6),
        "value": round_money(value, 6),
        "allocationPct": round_money(allocation, 4),
        "avg": 0.0,
        "score": score,
        "sources": data.get("sources", {}),
    }


def build_portfolio(raw: Dict[str, Any], prices: Dict[str, float]) -> Dict[str, Any]:
    merged: Dict[str, Dict[str, Any]] = {}
    source_summaries: Dict[str, Any] = {}

    available_usdt = 0.0
    calculated_total = 0.0
    valuation_total = _read_asset_valuation(raw)

    for source_name, payload in raw.items():
        if source_name == "asset_valuation":
            continue

        source_balances, source_usdt, source_total = _collect_balances_from_source(
            payload,
            prices,
        )

        _merge_source(merged, source_name, source_balances)

        available_usdt += source_usdt
        calculated_total += source_total

        source_summaries[source_name] = {
            "availableUsdt": round_money(source_usdt, 6),
            "estimatedUsd": round_money(source_total, 6),
            "currencies": sorted(source_balances.keys()),
        }

    estimated_total_usd = valuation_total if valuation_total > 0 else calculated_total
    capped_capital = min(available_usdt, settings.max_operating_capital)

    base_scores = {"ETH": 57, "XRP": 53, "SUI": 50, "BTC": 49, "SOL": 49, "BNB": 48}
    ordered_symbols = ["ETH"] + [s for s in SYMBOLS.keys() if s != "ETH"]

    assets: List[Dict[str, Any]] = []

    for sym in ordered_symbols:
        data = merged.get(sym, {"qty": 0.0, "value": 0.0, "sources": {}})
        price = prices.get(sym, 0.0)
        score = score_from_price(price, base_scores.get(sym, 50))

        assets.append(_asset_object(sym, data, price, estimated_total_usd, score))

    stable_assets: List[Dict[str, Any]] = []

    for ccy in sorted(STABLES):
        data = merged.get(ccy)
        if not data:
            continue

        stable_assets.append(_asset_object(ccy, data, 1.0, estimated_total_usd, 50))

    other_assets: List[Dict[str, Any]] = []

    for ccy, data in merged.items():
        if ccy in SYMBOLS or ccy in STABLES:
            continue

        qty = data.get("qty", 0.0)
        value = data.get("value", 0.0)

        if qty <= 0 and value <= 0:
            continue

        other_assets.append(_asset_object(ccy, data, 0.0, estimated_total_usd, 45))

    other_assets.sort(key=lambda x: x.get("value", 0.0), reverse=True)

    return {
        "availableUsdt": round_money(available_usdt, 6),
        "cappedCapital": round_money(capped_capital, 6),
        "estimatedTotalUsd": round_money(estimated_total_usd, 6),
        "calculatedTotalUsd": round_money(calculated_total, 6),
        "assetValuationTotalUsd": round_money(valuation_total, 6),
        "assets": assets,
        "stableAssets": stable_assets,
        "otherAssets": other_assets,
        "sourceSummaries": source_summaries,
        "ethQty": merged.get("ETH", {}).get("qty", 0.0),
    }
