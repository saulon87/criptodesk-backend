from datetime import datetime, timezone
from typing import Any

def iso_ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

def safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0
