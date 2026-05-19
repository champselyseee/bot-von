import asyncio
import logging
import os
import secrets
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import aiohttp
from aiohttp import web
from dotenv import load_dotenv
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from db import (
    confirm_payment,
    count_active_clients,
    get_or_create_user,
    get_vpn_client,
    has_provisioned_payment,
    init_db,
    mark_payment_provisioned,
    mark_trial_used,
    save_payment,
    set_vpn_expiry,
    upsert_vpn_client,
)
from vpn_api import VPNApiClient

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Config ────────────────────────────────────────────────────────────────

BOT_TOKEN    = os.environ["BOT_TOKEN"]
# ── Multi-server scaffold ──────────────────────────────────────────────────
# Each server needs its own VPN_API_URL_N, VPN_API_KEY_N env vars.
# Server 1 keeps the original names for backwards compatibility.
# To add server 2: set VPN_API_URL_2 and VPN_API_KEY_2 in Railway Variables.
# The subscription endpoint on each server handles its own /sub/{sub_id} output;
# the bot calls add_client / update_client on every server in VPN_SERVERS.
VPN_API_URL  = os.environ["VPN_API_URL"]
VPN_API_KEY  = os.environ["VPN_API_KEY"]
VPN_DOMAIN   = os.environ.get("VPN_DOMAIN", "camavali.duckdns.org")
VPN_SUB_PORT = os.environ.get("VPN_SUB_PORT", "2097")

def _load_servers() -> list:
    """Return list of (label, VPNApiClient) for every configured server."""
    servers = [("server_1", VPNApiClient(VPN_API_URL, VPN_API_KEY))]
    for n in range(2, 10):
        url = os.environ.get(f"VPN_API_URL_{n}")
        key = os.environ.get(f"VPN_API_KEY_{n}")
        if url and key:
            servers.append((f"server_{n}", VPNApiClient(url, key)))
    return servers

VPN_SERVERS: list = _load_servers()  # [(label, VPNApiClient), ...]
YOO_SHOP_ID  = os.environ.get("YOOMONEY_SHOP_ID", "")
YOO_SECRET   = os.environ.get("YOOMONEY_SECRET_KEY", "")
PORT         = int(os.environ.get("PORT", "8080"))
PRICE_2W     = int(os.environ.get("PRICE_2W", "149"))
PRICE_1M     = int(os.environ.get("PRICE_1M", "249"))

MAX_CLIENTS  = int(os.environ.get("MAX_CLIENTS", "30"))

TRIAL_SECS   = 86_400
PLAN_2W_SECS = 14 * 86_400
PLAN_1M_SECS = 30 * 86_400

PLAN_MAP = {
    "plan_2w": ("2 недели",  PLAN_2W_SECS, PRICE_2W),
    "plan_1m": ("1 месяц",   PLAN_1M_SECS, PRICE_1M),
}

MSK = timezone(timedelta(hours=3))

vpn = VPN_SERVERS[0][1]  # primary server — used directly by existing code

_client_create_lock = asyncio.Lock()


class ClientLimitReached(Exception):
    pass

# Set in main() after Application is built; used by the webhook handler
_app_bot: Optional[Bot] = None


# ─── Helpers ───────────────────────────────────────────────────────────────

def fmt_dt(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=MSK).strftime("%d.%m.%Y %H:%M МСК")


def links_text(sub_id: str, expires_at: int, plan_name: str) -> str:
    connect_url = f"https://{VPN_DOMAIN}:{VPN_SUB_PORT}/connect/{sub_id}"
    return (
        f"✅ <b>VPN подключение активно</b>\n"
        f"📋 Тариф: <b>{plan_name}</b>\n"
        f"⏰ Действует до: <b>{fmt_dt(expires_at)}</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>📡 Как работает роутинг</b>\n\n"
        f"Российские сайты — ВКонтакте, Госуслуги, банки, Авито, Яндекс — работают <b>напрямую без VPN</b>: быстро и без задержек.\n\n"
        f"Заблокированные и зарубежные — Instagram, YouTube, Google, Spotify — идут <b>через VPN</b> автоматически.\n\n"
        f"Переключать вручную ничего не нужно. Всё происходит само.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>📲 Как подключиться:</b>\n\n"
        f"Нажми кнопку ниже или открой ссылку — автоматически откроется hApp и добавит подписку:\n"
        f"<code>{connect_url}</code>"
    )


def links_keyboard(sub_id: str, extra_rows: list | None = None) -> InlineKeyboardMarkup:
    connect_url = f"https://{VPN_DOMAIN}:{VPN_SUB_PORT}/connect/{sub_id}"
    rows = [[InlineKeyboardButton("📲 Добавить в hApp", url=connect_url)]]
    if extra_rows:
        rows.extend(extra_rows)
    return InlineKeyboardMarkup(rows)


def main_keyboard(trial_used: bool, has_active: bool) -> InlineKeyboardMarkup:
    rows = []
    if not trial_used:
        rows.append([InlineKeyboardButton(
            "🆓 Попробовать бесплатно (1 день)", callback_data="trial"
        )])
    if has_active:
        rows.append([InlineKeyboardButton(
            "📱 Мои ссылки для подключения", callback_data="mylinks"
        )])
    rows.append([InlineKeyboardButton("💳 Купить подписку", callback_data="buy")])
    rows.append([InlineKeyboardButton("ℹ️ Поддержка", callback_data="support")])
    return InlineKeyboardMarkup(rows)


def buy_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📅 2 недели — {PRICE_2W} ₽", callback_data="plan_2w")],
        [InlineKeyboardButton(f"🗓 1 месяц — {PRICE_1M} ₽",  callback_data="plan_1m")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_main")],
    ])


def back_button(cb: str = "back_main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data=cb)]])


# ─── VPN client management ─────────────────────────────────────────────────

async def create_or_extend_vpn_client(user_id: int, extra_seconds: int) -> tuple[str, int]:
    """
    Creates a new VPN client or extends an existing one.
    Calls vpn-api.py on the server, then updates local DB.
    Returns (sub_id, expires_at_unix).
    """
    existing = get_vpn_client(user_id)
    now = int(time.time())

    if existing:
        # Stack on top of existing expiry only when renewing an already-paid plan.
        # For the first paid purchase (after trial), start from now to avoid
        # trial time bleeding into the paid subscription period.
        if has_provisioned_payment(user_id):
            base = max(existing["expires_at"], now)
        else:
            base = now
        new_exp    = base + extra_seconds
        expires_ms = new_exp * 1000
        for _label, srv in VPN_SERVERS:
            try:
                await srv.update_client(existing["email"], expires_ms)
            except Exception as e:
                logger.error("update_client failed on %s for user=%s: %s", _label, user_id, e)
        set_vpn_expiry(user_id, new_exp)
        return existing["sub_id"], new_exp
    else:
        async with _client_create_lock:
            if count_active_clients() >= MAX_CLIENTS:
                raise ClientLimitReached()

            email      = f"tg_{user_id}"
            sub_id     = secrets.token_hex(8)
            password   = secrets.token_urlsafe(24)
            expires_at = now + extra_seconds
            expires_ms = expires_at * 1000

            for _label, srv in VPN_SERVERS:
                try:
                    await srv.add_client(email, password, sub_id, expires_ms)
                except Exception as e:
                    logger.error("add_client failed on %s for user=%s: %s", _label, user_id, e)

            try:
                upsert_vpn_client(user_id, str(uuid.uuid4()), email, sub_id, password, 0, expires_at)
            except Exception as db_err:
                logger.critical(
                    "DB write failed after vpn-api.add_client — orphaned server client! "
                    "user_id=%s email=%s sub_id=%s — %s",
                    user_id, email, sub_id, db_err,
                )
                raise

            return sub_id, expires_at


# ─── YooMoney payment creation ─────────────────────────────────────────────

async def create_yoomoney_payment(
    user_id: int, plan_key: str, plan_name: str, price: int
) -> tuple[str, str]:
    """Returns (confirmation_url, payment_id)."""
    descriptions = {
        "plan_2w": "CamilleVPN — 2 недели",
        "plan_1m": "CamilleVPN — 1 месяц",
    }
    async with aiohttp.ClientSession() as s:
        async with s.post(
            "https://api.yookassa.ru/v3/payments",
            auth=aiohttp.BasicAuth(YOO_SHOP_ID, YOO_SECRET),
            headers={
                "Idempotence-Key": str(uuid.uuid4()),
                "Content-Type": "application/json",
            },
            json={
                "amount":       {"value": f"{price}.00", "currency": "RUB"},
                "confirmation": {"type": "redirect", "return_url": "https://t.me/"},
                "capture":      True,
                "description":  descriptions.get(plan_key, plan_name),
                "metadata":     {"user_id": str(user_id), "plan": plan_key},
            },
            timeout=aiohttp.ClientTimeout(total=15),
        ) as r:
            if r.status not in (200, 201):
                err = await r.text()
                raise RuntimeError(f"YooKassa {r.status}: {err[:300]}")
            data = await r.json()
    return data["confirmation"]["confirmation_url"], data["id"]


# ─── Telegram handlers ─────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user   = update.effective_user
    udata  = get_or_create_user(user.id, user.username)
    now    = int(time.time())
    client = get_vpn_client(user.id)
    has_active = bool(client and client["expires_at"] > now)

    text = (
        "👋 <b>CamilleVPN</b>\n\n"
        "Быстрый VPN на протоколе Hysteria2.\n"
        "Работает при смене WiFi ↔ мобильный интернет.\n"
        "РУ-сайты идут напрямую (split tunneling).\n\n"
    )
    if has_active:
        text += f"📶 Подписка активна до <b>{fmt_dt(client['expires_at'])}</b>\n\n"
    elif not udata["trial_used"]:
        text += "🆓 Доступен бесплатный пробный период — 1 день!\n\n"

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=main_keyboard(bool(udata["trial_used"]), has_active),
    )


async def cmd_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user   = update.effective_user
    now    = int(time.time())
    client = get_vpn_client(user.id)
    if not client or client["expires_at"] <= now:
        await update.message.reply_text(
            "❌ Нет активной подписки.\n\n/start → Купить подписку"
        )
        return
    await update.message.reply_text(
        links_text(client["sub_id"], client["expires_at"], "Активная"),
        parse_mode="HTML",
        reply_markup=links_keyboard(client["sub_id"]),
    )


async def cb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q     = update.callback_query
    await q.answer()
    cdata = q.data
    user  = q.from_user
    now   = int(time.time())
    udata = get_or_create_user(user.id, user.username)
    client = get_vpn_client(user.id)
    has_active = bool(client and client["expires_at"] > now)

    if cdata == "back_main":
        await q.message.edit_text(
            "👋 <b>CamilleVPN</b> — главное меню:",
            parse_mode="HTML",
            reply_markup=main_keyboard(bool(udata["trial_used"]), has_active),
        )
        return

    if cdata == "support":
        await q.message.edit_text(
            "ℹ️ По вопросам пишите: @champselyseee",
            reply_markup=back_button(),
        )
        return

    if cdata == "mylinks":
        if not has_active:
            await q.message.edit_text(
                "❌ Подписка не активна. Выбери тариф:",
                reply_markup=buy_keyboard(),
            )
            return
        await q.message.edit_text(
            links_text(client["sub_id"], client["expires_at"], "Активная"),
            parse_mode="HTML",
            reply_markup=links_keyboard(client["sub_id"], [
                [InlineKeyboardButton("💳 Продлить подписку", callback_data="buy")],
                [InlineKeyboardButton("⬅️ Назад", callback_data="back_main")],
            ]),
        )
        return

    if cdata == "trial":
        if udata["trial_used"] or get_vpn_client(user.id):
            await q.message.edit_text(
                "⚠️ Пробный период уже использован. Выбери тариф:",
                reply_markup=buy_keyboard(),
            )
            return
        try:
            await q.message.edit_text("⏳ Создаю подключение...")
            sub_id, exp = await create_or_extend_vpn_client(user.id, TRIAL_SECS)
            mark_trial_used(user.id)
            await q.message.edit_text(
                links_text(sub_id, exp, "Пробный период (1 день)"),
                parse_mode="HTML",
                reply_markup=links_keyboard(sub_id, [
                    [InlineKeyboardButton("💳 Купить подписку", callback_data="buy")],
                ]),
            )
        except ClientLimitReached:
            await q.message.edit_text(
                "😔 Все слоты заняты — сервис временно не принимает новых пользователей.\n"
                "Напиши в поддержку, мы добавим тебя в список ожидания.",
                reply_markup=back_button("support"),
            )
        except Exception as e:
            logger.error("trial error user=%s: %s", user.id, e)
            await q.message.edit_text(
                "❌ Ошибка создания подключения. Попробуй позже или напиши в поддержку.",
                reply_markup=back_button("support"),
            )
        return

    if cdata == "buy":
        active_text = ""
        if has_active:
            active_text = f"📶 Текущая подписка до <b>{fmt_dt(client['expires_at'])}</b>\n\n"
        await q.message.edit_text(
            f"{active_text}💳 <b>Выбери тариф:</b>",
            parse_mode="HTML",
            reply_markup=buy_keyboard(),
        )
        return

    if cdata in PLAN_MAP:
        plan_name, plan_secs, price = PLAN_MAP[cdata]
        if not YOO_SHOP_ID or not YOO_SECRET:
            await q.message.edit_text(
                "⚠️ Оплата временно недоступна. Обратитесь в поддержку.",
                reply_markup=back_button("support"),
            )
            return
        if not has_active and count_active_clients() >= MAX_CLIENTS:
            await q.message.edit_text(
                "😔 Все слоты заняты — сервис временно не принимает новых пользователей.\n"
                "Напиши в поддержку, мы добавим тебя в список ожидания.",
                reply_markup=back_button("support"),
            )
            return
        try:
            pay_url, yoo_id = await create_yoomoney_payment(user.id, cdata, plan_name, price)
            save_payment(yoo_id, user.id, cdata, float(price))
            await q.message.edit_text(
                f"💳 <b>{plan_name} — {price} ₽</b>\n\n"
                f"Нажми «Оплатить», затем вернись в бот.\n"
                f"Подписка активируется автоматически после оплаты.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 Оплатить", url=pay_url)],
                    [InlineKeyboardButton("⬅️ Назад", callback_data="buy")],
                ]),
            )
        except Exception as e:
            logger.error("payment create error user=%s: %s", user.id, e)
            await q.message.edit_text(
                "❌ Ошибка создания платежа. Попробуй позже.",
                reply_markup=buy_keyboard(),
            )
        return


# ─── Web server ─────────────────────────────────────────────────────────────

async def handle_yoomoney_webhook(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.Response(status=400)

    if body.get("event") != "payment.succeeded":
        return web.Response(status=200)

    obj  = body.get("object", {})
    meta = obj.get("metadata", {})
    yoo_id = obj.get("id", "")

    try:
        user_id = int(meta.get("user_id", 0))
    except (ValueError, TypeError):
        return web.Response(status=200)

    plan_key = meta.get("plan", "")
    if not user_id or not plan_key or not yoo_id:
        return web.Response(status=200)

    # Extract real amount from webhook body (falls back to 0.0 if missing)
    try:
        real_amount = float(obj.get("amount", {}).get("value", 0.0))
    except (TypeError, ValueError):
        real_amount = 0.0

    # Ensure payment row exists even if bot restarted between payment creation and webhook
    save_payment(yoo_id, user_id, plan_key, real_amount)

    # Idempotency guard — process each payment exactly once
    result = confirm_payment(yoo_id)
    if not result:
        return web.Response(status=200)
    _, confirmed_plan = result

    plan_info = PLAN_MAP.get(confirmed_plan)
    if not plan_info:
        logger.error("unknown plan in webhook: %s", confirmed_plan)
        return web.Response(status=200)

    plan_name, plan_secs, _ = plan_info

    # Ensure user row exists (edge case: paid without /start)
    get_or_create_user(user_id, None)

    try:
        sub_id, exp = await create_or_extend_vpn_client(user_id, plan_secs)
        mark_payment_provisioned(yoo_id)
        bot = _app_bot
        if bot:
            await bot.send_message(
                chat_id=user_id,
                text=(
                    f"✅ <b>Оплата прошла! Подписка «{plan_name}» активирована.</b>\n\n"
                    + links_text(sub_id, exp, plan_name)
                ),
                parse_mode="HTML",
                reply_markup=links_keyboard(sub_id),
            )
        logger.info(
            "webhook: activated plan=%s for user=%s until=%s",
            confirmed_plan, user_id, fmt_dt(exp),
        )
    except ClientLimitReached:
        logger.error("webhook: client limit reached, cannot provision user=%s", user_id)
        bot = _app_bot
        if bot:
            await bot.send_message(
                chat_id=user_id,
                text=(
                    "✅ Оплата прошла, но все слоты заняты — мы не смогли активировать подписку автоматически.\n\n"
                    "Напиши в поддержку @champselyseee, вопрос решим вручную."
                ),
            )
    except Exception as e:
        logger.error("webhook processing error user=%s: %s", user_id, e)
        bot = _app_bot
        if bot:
            await bot.send_message(
                chat_id=user_id,
                text=(
                    "✅ Оплата прошла, но при активации возникла ошибка.\n\n"
                    "Напиши в поддержку @champselyseee — разберёмся вручную."
                ),
            )

    return web.Response(status=200)


async def handle_health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def run_web():
    app = web.Application()
    app.router.add_post("/yoomoney/webhook", handle_yoomoney_webhook)
    app.router.add_get("/health", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    logger.info("Web server started on :%s", PORT)


# ─── Entry point ────────────────────────────────────────────────────────────

async def main():
    global _app_bot

    init_db()
    await run_web()

    tg = ApplicationBuilder().token(BOT_TOKEN).build()
    _app_bot = tg.bot

    tg.add_handler(CommandHandler("start", cmd_start))
    tg.add_handler(CommandHandler("links", cmd_links))
    tg.add_handler(CallbackQueryHandler(cb_handler))

    async with tg:
        await tg.start()
        await tg.updater.start_polling(drop_pending_updates=True)
        logger.info("Bot polling started")
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
