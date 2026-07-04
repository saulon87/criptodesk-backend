from datetime import datetime, timezone
from typing import Any


def iso_ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def first_positive(*values: Any) -> float:
    for value in values:
        amount = safe_float(value)
        if amount > 0:
            return amount
    return 0.0


def round_money(value: Any, decimals: int = 6) -> float:
    return round(safe_float(value), decimals)
