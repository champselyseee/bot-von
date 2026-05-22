from __future__ import annotations
import uuid
import httpx
import logging
from typing import Optional

log = logging.getLogger(__name__)

_BASE = "https://api.yookassa.ru/v3"


class YooKassaClient:
    def __init__(self, shop_id: str, secret_key: str):
        self._auth = (shop_id, secret_key)
        self._enabled = bool(shop_id and secret_key)

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def create_payment(
        self,
        amount: int,
        description: str,
        return_url: str,
        metadata: dict,
    ) -> tuple[str, str]:
        """Create payment. Returns (payment_id, confirmation_url)."""
        payload = {
            "amount": {"value": f"{amount}.00", "currency": "RUB"},
            "confirmation": {"type": "redirect", "return_url": return_url},
            "capture": True,
            "description": description,
            "metadata": {k: str(v) for k, v in metadata.items()},
        }
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                f"{_BASE}/payments",
                json=payload,
                auth=self._auth,
                headers={"Idempotency-Key": str(uuid.uuid4())},
            )
            if r.is_error:
                log.error("YooKassa %s error body: %s", r.status_code, r.text)
            r.raise_for_status()
            data = r.json()
            return data["id"], data["confirmation"]["confirmation_url"]

    async def get_payment(self, payment_id: str) -> dict:
        """Fetch payment status from YooKassa (used to verify webhook)."""
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{_BASE}/payments/{payment_id}", auth=self._auth)
            r.raise_for_status()
            return r.json()
