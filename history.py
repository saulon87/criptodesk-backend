from typing import Any, Dict, List


_HISTORY: List[Dict[str, Any]] = []


def add_event(event: Dict[str, Any]) -> None:
    _HISTORY.insert(0, event)
    del _HISTORY[100:]


def latest_events(limit: int = 20) -> List[Dict[str, Any]]:
    return _HISTORY[:limit]
