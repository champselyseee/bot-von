from __future__ import annotations
import httpx
import logging

log = logging.getLogger(__name__)


class VPNClient:
    def __init__(self, api_url: str, api_key: str):
        self._url = api_url.rstrip("/")
        self._headers = {"X-API-Key": api_key, "Content-Type": "application/json"}

    async def add_client(
        self, email: str, password: str, sub_id: str, expires_at: int
    ) -> bool:
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post(
                    f"{self._url}/client/add",
                    json={
                        "email": email,
                        "password": password,
                        "sub_id": sub_id,
                        "expires_ms": expires_at * 1000,
                    },
                    headers=self._headers,
                )
                if r.status_code != 200:
                    log.error("VPN add_client %s → %s %s", email, r.status_code, r.text)
                return r.status_code == 200
        except Exception as e:
            log.exception("VPN add_client error: %s", e)
            return False

    async def remove_client(self, email: str, sub_id: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(
                    f"{self._url}/client/remove",
                    json={"email": email, "sub_id": sub_id},
                    headers=self._headers,
                )
                return r.status_code == 200
        except Exception as e:
            log.exception("VPN remove_client error: %s", e)
            return False

    async def update_client(self, email: str, expires_at: int) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(
                    f"{self._url}/client/update",
                    json={"email": email, "expires_ms": expires_at * 1000},
                    headers=self._headers,
                )
                return r.status_code == 200
        except Exception as e:
            log.exception("VPN update_client error: %s", e)
            return False

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get(f"{self._url}/health")
                return r.status_code == 200
        except Exception:
            return False
