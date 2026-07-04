import base64
import hashlib
import hmac
from typing import Any, Dict, List, Tuple

import httpx

from config import settings
from utils import iso_ts

class OKXClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    def _require_credentials(self) -> None:
        missing = []
        if not settings.api_key:
            missing.append("OKX_API_KEY")
        if not settings.secret_key:
            missing.append("OKX_SECRET_KEY")
        if not settings.passphrase:
            missing.append("OKX_PASSPHRASE")
        if missing:
            raise RuntimeError("Faltan variables de entorno: " + ", ".join(missing))

    def _headers(self, method: str, path: str, body: str = "") -> Dict[str, str]:
        self._require_credentials()
        timestamp = iso_ts()
        prehash = f"{timestamp}{method.upper()}{path}{body}"
        signature = base64.b64encode(
            hmac.new(settings.secret_key.encode("utf-8"), prehash.encode("utf-8"), hashlib.sha256).digest()
        ).decode("utf-8")
        return {
            "OK-ACCESS-KEY": settings.api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": settings.passphrase,
            "Content-Type": "application/json",
            "x-simulated-trading": "0",
        }

    async def get(self, path: str) -> Dict[str, Any]:
        response = await self.client.get(f"{settings.okx_base}{path}", headers=self._headers("GET", path, ""))
        response.raise_for_status()
        return response.json()

    async def safe_get(self, path: str) -> Tuple[Dict[str, Any] | None, str | None]:
        try:
            return await self.get(path), None
        except Exception as exc:
            return None, f"{path}: {str(exc)}"

    async def load_raw_sources(self) -> Tuple[Dict[str, Any], List[str]]:
        warnings: List[str] = []
        raw: Dict[str, Any] = {}
        endpoints = {
            "trading": "/api/v5/account/balance",
            "funding": "/api/v5/asset/balances",
            "asset_valuation": "/api/v5/asset/asset-valuation?ccy=USD",
        }
        for name, path in endpoints.items():
            data, warning = await self.safe_get(path)
            if data is not None:
                raw[name] = data
            if warning:
                warnings.append(warning)
        return raw, warnings
