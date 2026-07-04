import time
from typing import Any, Dict, Optional


class TTLCache:
    def __init__(self) -> None:
        self._data: Dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Optional[Any]:
        item = self._data.get(key)
        if not item:
            return None

        expires_at, value = item
        if time.time() > expires_at:
            self._data.pop(key, None)
            return None

        return value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        self._data[key] = (time.time() + ttl_seconds, value)

    def clear(self) -> None:
        self._data.clear()


cache = TTLCache()
