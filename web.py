"""aiohttp web server: YooKassa webhook + connect.html page."""
from __future__ import annotations
import json
import logging
import os
from pathlib import Path
from urllib.parse import quote

from aiohttp import web

log = logging.getLogger(__name__)

_TEMPLATE = (Path(__file__).parent / "connect.html").read_text(encoding="utf-8")


def _build_connect_page(config, sub_id: str) -> str:
    sub_url = f"{config.sub_base_url}/sub/{sub_id}"
    crypt_link = f"happ://import/sub?url={quote(sub_url, safe='')}"
    return (
        _TEMPLATE
        .replace("CRYPT_LINK_HERE", crypt_link)
        .replace("SUB_URL_HERE", sub_url)
        .replace("ROUTE_B64_HERE", config.ROUTE_B64)
    )


def create_app(bot, config, vpn) -> web.Application:
    app = web.Application()

    # ── /connect/{sub_id} ────────────────────────────────────────────────────

    async def connect_page(request: web.Request) -> web.Response:
        sub_id = request.match_info["sub_id"]
        html = _build_connect_page(config, sub_id)
        return web.Response(text=html, content_type="text/html")

    # ── /payment/webhook ─────────────────────────────────────────────────────

    async def payment_webhook(request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except Exception:
            return web.Response(status=400)

        event = payload.get("event", "")
        if event != "payment.succeeded":
            return web.Response(status=200)  # Acknowledge other events silently

        payment_data = payload.get("object", {})
        yookassa_id = payment_data.get("id", "")
        if not yookassa_id:
            return web.Response(status=400)

        # Re-verify with YooKassa API (security)
        from payments import YooKassaClient
        yk: YooKassaClient = request.app["payments"]
        try:
            verified = await yk.get_payment(yookassa_id)
            if verified.get("status") != "succeeded":
                log.warning("Webhook: payment %s not succeeded (status=%s)", yookassa_id, verified.get("status"))
                return web.Response(status=200)
        except Exception as e:
            log.exception("Cannot verify payment %s: %s", yookassa_id, e)
            return web.Response(status=500)

        # Load pending payment from DB
        import db as database
        payment = await database.get_payment(config.db_path, yookassa_id)
        if not payment:
            log.warning("Webhook: unknown payment %s", yookassa_id)
            return web.Response(status=200)

        if payment["status"] != "pending":
            return web.Response(status=200)  # Already processed

        tg_id = payment["tg_id"]
        user_id = payment["user_id"]
        plan = payment["plan"]

        log.info("Webhook: payment %s succeeded for tg_id=%s plan=%s", yookassa_id, tg_id, plan)

        from handlers.buy import provision_after_payment
        await provision_after_payment(config, vpn, bot, tg_id, user_id, plan, yookassa_id)

        return web.Response(status=200)

    # ── /health ───────────────────────────────────────────────────────────────

    async def health(request: web.Request) -> web.Response:
        return web.Response(text="ok")

    app.router.add_get("/connect/{sub_id}", connect_page)
    app.router.add_post("/payment/webhook", payment_webhook)
    app.router.add_get("/health", health)
    app.router.add_get("/", health)

    app["payments"] = None  # will be set in bot.py
    return app
