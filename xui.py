import asyncio
import json
import logging

import aiohttp

logger = logging.getLogger(__name__)


class XUIClient:
    """Async client for 3x-ui panel API (session cookie auth)."""

    def __init__(self, base_url: str, username: str, password: str):
        # base_url includes path prefix, e.g. http://host:port/secret_path
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        # unsafe=True needed when connecting to bare IP addresses
        self._jar = aiohttp.CookieJar(unsafe=True)
        self._logged_in = False
        self._login_lock = asyncio.Lock()

    async def _login(self):
        async with aiohttp.ClientSession(cookie_jar=self._jar) as s:
            async with s.post(
                f"{self.base_url}/login",
                data={"username": self.username, "password": self.password},
                ssl=False,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                text = await r.text()
                try:
                    data = json.loads(text)
                except Exception:
                    raise RuntimeError(
                        f"3x-ui login: non-JSON response ({r.status}): {text[:200]}"
                    )
        if not data.get("success"):
            raise RuntimeError(f"3x-ui login failed: {data.get('msg', data)}")
        self._logged_in = True
        logger.info("3x-ui login OK")

    async def _req(self, method: str, path: str, **kwargs) -> dict:
        kwargs.setdefault("ssl", False)
        kwargs.setdefault("timeout", aiohttp.ClientTimeout(total=15))

        # Ensure logged in (lock prevents concurrent logins)
        async with self._login_lock:
            if not self._logged_in:
                await self._login()

        url = f"{self.base_url}{path}"

        async with aiohttp.ClientSession(cookie_jar=self._jar) as s:
            async with s.request(method, url, **kwargs) as r:
                if r.status != 401:
                    return await r.json(content_type=None)

        # 401: re-login once and retry
        async with self._login_lock:
            self._logged_in = False
            await self._login()

        async with aiohttp.ClientSession(cookie_jar=self._jar) as s:
            async with s.request(method, url, **kwargs) as r:
                data = await r.json(content_type=None)
                if not data.get("success"):
                    raise RuntimeError(f"3x-ui request failed after re-login: {data.get('msg', data)}")
                return data

    async def add_client(self, inbound_id: int, client: dict) -> None:
        """Add a new client to the given inbound."""
        settings = json.dumps({"clients": [client]})
        data = await self._req("POST", "/xui/inbound/addClient", json={
            "id": inbound_id,
            "settings": settings,
        })
        if not data.get("success"):
            raise RuntimeError(f"add_client failed: {data.get('msg', data)}")
        logger.info("3x-ui: created client %s in inbound %s", client.get("email"), inbound_id)

    async def update_client(self, inbound_id: int, client_uuid: str, client: dict) -> None:
        """Update an existing client (full object required)."""
        settings = json.dumps({"clients": [client]})
        data = await self._req(
            "POST",
            f"/xui/inbound/{inbound_id}/updateClient/{client_uuid}",
            json={"id": inbound_id, "settings": settings},
        )
        if not data.get("success"):
            raise RuntimeError(f"update_client failed: {data.get('msg', data)}")
        logger.info(
            "3x-ui: updated client %s, expiryTime=%s",
            client.get("email"), client.get("expiryTime"),
        )
