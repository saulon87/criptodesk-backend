import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    okx_base: str = "https://www.okx.com"
    max_operating_capital: float = 9.44
    request_timeout: float = 15.0
    cache_ttl_seconds: int = 45

    @property
    def api_key(self) -> str:
        return os.getenv("OKX_API_KEY", "").strip()

    @property
    def secret_key(self) -> str:
        return os.getenv("OKX_SECRET_KEY", "").strip()

    @property
    def passphrase(self) -> str:
        return os.getenv("OKX_PASSPHRASE", "").strip()

settings = Settings()
