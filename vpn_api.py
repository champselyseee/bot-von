"""
Async HTTP clients for the VPN management layer.

VPNApiClient  → vpn-api.py  (port 8765)  add/update clients in all 4 stores
SubApiClient  → hy2-sub.py  (port 2097)  register dynamic sub client in-memory
"""

import ssl
import aiohttp

_TIMEOUT = aiohttp.ClientTimeout(total=20)

# Reusable SSL context that skips cert verification (self-signed server cert)
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


class VPNApiClient:
    """Client for vpn-api.py running on port 8765."""

    def __init__(self, base_url: str, api_key: str):
        self._base = base_url.rstrip("/")
        self._headers = {"X-API-Key": api_key, "Content-Type": "application/json"}

    async def add_client(self, email: str, password: str, sub_id: str, expires_ms: int):
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{self._base}/client/add",
                headers=self._headers,
                json={"email": email, "password": password, "sub_id": sub_id, "expires_ms": expires_ms},
                timeout=_TIMEOUT,
            ) as r:
                data = await r.json()
                if not data.get("ok"):
                    raise RuntimeError(f"vpn-api add_client error: {data.get('error')}")
                return data

    async def update_client(self, email: str, expires_ms: int):
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{self._base}/client/update",
                headers=self._headers,
                json={"email": email, "expires_ms": expires_ms},
                timeout=_TIMEOUT,
            ) as r:
                data = await r.json()
                if not data.get("ok"):
                    raise RuntimeError(f"vpn-api update_client error: {data.get('error')}")
                return data


class SubApiClient:
    """Client for hy2-sub.py /client/add endpoint (dynamic client registration)."""

    def __init__(self, base_url: str, api_key: str):
        self._base = base_url.rstrip("/")
        self._headers = {"X-API-Key": api_key, "Content-Type": "application/json"}

    async def register_client(self, sub_id: str, email: str, password: str):
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{self._base}/client/add",
                headers=self._headers,
                json={"sub_id": sub_id, "email": email, "password": password},
                ssl=_ssl_ctx,
                timeout=_TIMEOUT,
            ) as r:
                data = await r.json()
                if not data.get("ok"):
                    raise RuntimeError(f"hy2-sub register error: {data.get('error')}")
                return data
