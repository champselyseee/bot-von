import logging

import aiohttp

logger = logging.getLogger(__name__)


class VPNApiClient:
    """Client for the local vpn-api.py management service on the VPN server."""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.headers = {"X-API-Key": api_key, "Content-Type": "application/json"}

    async def _post(self, path: str, payload: dict) -> dict:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{self.base_url}{path}",
                json=payload,
                headers=self.headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                try:
                    data = await r.json(content_type=None)
                except Exception:
                    text = await r.text()
                    raise RuntimeError(f"vpn-api {r.status}: {text[:200]}")
                if r.status == 409:
                    raise RuntimeError(f"conflict: {data.get('error', data)}")
                if not data.get("ok"):
                    raise RuntimeError(f"vpn-api error {r.status}: {data.get('error', data)}")
                return data

    async def add_client(self, email: str, password: str, sub_id: str, expires_ms: int) -> None:
        await self._post("/client/add", {
            "email":      email,
            "password":   password,
            "sub_id":     sub_id,
            "expires_ms": expires_ms,
        })
        logger.info("vpn-api: added client %s sub_id=%s", email, sub_id)

    async def update_client(self, email: str, expires_ms: int) -> None:
        await self._post("/client/update", {
            "email":      email,
            "expires_ms": expires_ms,
        })
        logger.info("vpn-api: updated client %s expires_ms=%s", email, expires_ms)
