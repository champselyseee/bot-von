"""Camille VPN Bot — entry point."""
from __future__ import annotations
import asyncio
import logging
import time

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import load_config
from db import init_db, get_expired_subs, set_sub_status
from vpn import VPNClient
from payments import YooKassaClient
from handlers import register_all
from web import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("bot")


async def expiry_checker(bot: Bot, config, vpn: VPNClient):
    """Background task: revoke expired subscriptions every 5 min."""
    while True:
        try:
            expired = await get_expired_subs(config.db_path)
            for sub in expired:
                log.info("Expiring sub %s (tg=%s)", sub["sub_id"], sub["tg_id"])
                await vpn.remove_client(sub["email"], sub["sub_id"])
                await set_sub_status(config.db_path, sub["sub_id"], "expired")
                try:
                    await bot.send_message(
                        sub["tg_id"],
                        "⏳ <b>Подписка Camille VPN истекла.</b>\n\n"
                        "Нажми /start чтобы продлить.",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
        except Exception as e:
            log.exception("expiry_checker error: %s", e)
        await asyncio.sleep(300)  # every 5 minutes


async def main():
    config = load_config()
    log.info("Starting Camille VPN Bot (base_url=%s)", config.base_url)

    await init_db(config.db_path)

    vpn = VPNClient(config.vpn_api_url, config.vpn_api_key)
    payments = YooKassaClient(config.yookassa_shop_id, config.yookassa_secret_key)

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    register_all(dp)

    # Web app (webhook + connect page)
    app = create_app(bot, config, vpn)
    app["payments"] = payments

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.port)
    await site.start()
    log.info("Web server on :%s", config.port)

    # Start background expiry checker
    asyncio.create_task(expiry_checker(bot, config, vpn))

    # Start polling (works in dev and on Railway without webhook setup)
    log.info("Starting polling...")
    await dp.start_polling(
        bot,
        config=config,
        vpn=vpn,
        payments=payments,
        allowed_updates=["message", "callback_query"],
    )


if __name__ == "__main__":
    asyncio.run(main())
