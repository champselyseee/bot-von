import asyncio
import logging
import os
import secrets
import time
import uuid
from datetime import datetime, timezone, timedelta

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
    get_or_create_user,
    get_vpn_client,
    init_db,
    mark_trial_used,
    save_payment,
    set_vpn_expiry,
    upsert_vpn_client,
)
from xui import XUIClient

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Config ────────────────────────────────────────────────────────────────

BOT_TOKEN       = os.environ["BOT_TOKEN"]
XUI_URL         = os.environ["XUI_URL"]          # e.g. http://78.40.117.96:54321/2298a2bf9987b044
XUI_USERNAME    = os.environ.get("XUI_USERNAME", "admin")
XUI_PASSWORD    = os.environ.get("XUI_PASSWORD", "admin123")
XUI_HY2_INBOUND = int(os.environ.get("XUI_HY2_INBOUND_ID", "1"))
VPN_DOMAIN      = os.environ.get("VPN_DOMAIN", "camavali.duckdns.org")
VPN_SUB_PORT    = os.environ.get("VPN_SUB_PORT", "2097")
YOO_SHOP_ID     = os.environ.get("YOOMONEY_SHOP_ID", "")
YOO_SECRET      = os.environ.get("YOOMONEY_SECRET_KEY", "")
PORT            = int(os.environ.get("PORT", "8080"))
PRICE_2W        = int(os.environ.get("PRICE_2W", "149"))
PRICE_1M        = int(os.environ.get("PRICE_1M", "249"))

TRIAL_SECS   = 86_400
PLAN_2W_SECS = 14 * 86_400
PLAN_1M_SECS = 30 * 86_400

PLAN_MAP = {
    "plan_2w": ("2 недели",  PLAN_2W_SECS, PRICE_2W),
    "plan_1m": ("1 месяц",   PLAN_1M_SECS, PRICE_1M),
}

MSK = timezone(timedelta(hours=3))

xui = XUIClient(XUI_URL, XUI_USERNAME, XUI_PASSWORD)

# Set in main() after Application is built; used by the webhook handler
_app_bot: Bot | None = None


# ─── Helpers ───────────────────────────────────────────────────────────────

def fmt_dt(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=MSK).strftime("%d.%m.%Y %H:%M МСК")


def links_text(sub_id: str, expires_at: int, plan_name: str) -> str:
    setup_url = f"http://{VPN_DOMAIN}/setup/{sub_id}"
    sub_url   = f"https://{VPN_DOMAIN}:{VPN_SUB_PORT}/sub/{sub_id}"
    return (
        f"✅ <b>VPN подключение активно</b>\n"
        f"📋 Тариф: <b>{plan_name}</b>\n"
        f"⏰ Действует до: <b>{fmt_dt(expires_at)}</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>📱 Как подключиться (приложение Happ):</b>\n\n"
        f"1️⃣ Открой эту ссылку в браузере на телефоне:\n"
        f"<code>{setup_url}</code>\n\n"
        f"2️⃣ Нажми <b>«Добавить в Happ»</b> — установится профиль маршрутизации "
        f"(РУ-сайты идут напрямую без VPN)\n\n"
        f"3️⃣ Нажми <b>«Скопировать ссылку»</b>, вставь в Happ → Subscriptions\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📎 Прямая ссылка на подписку (для других клиентов):\n"
        f"<code>{sub_url}</code>"
    )


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

def _build_client_obj(
    client_uuid: str, email: str, password: str,
    sub_id: str, expires_at: int, user_id: int,
) -> dict:
    return {
        "id":         client_uuid,
        "email":      email,
        "password":   password,
        "subId":      sub_id,
        "expiryTime": expires_at * 1000,   # 3x-ui expects milliseconds
        "enable":     True,
        "limitIp":    0,
        "totalGB":    0,
        "tgId":       str(user_id),
        "comment":    "",
    }


async def create_or_extend_vpn_client(user_id: int, extra_seconds: int) -> tuple[str, int]:
    """
    Creates a new 3x-ui client or extends the expiry of an existing one.
    Returns (sub_id, expires_at_unix).
    3x-ui is always updated before the local DB.
    """
    existing = get_vpn_client(user_id)
    now = int(time.time())

    if existing:
        current_exp = max(existing["expires_at"], now)
        new_exp = current_exp + extra_seconds
        client = _build_client_obj(
            existing["client_uuid"], existing["email"], existing["password"],
            existing["sub_id"], new_exp, user_id,
        )
        await xui.update_client(existing["inbound_id"], existing["client_uuid"], client)
        set_vpn_expiry(user_id, new_exp)
        return existing["sub_id"], new_exp
    else:
        client_uuid = str(uuid.uuid4())
        email       = f"tg_{user_id}"
        sub_id      = secrets.token_hex(8)
        password    = secrets.token_urlsafe(24)
        expires_at  = now + extra_seconds
        client = _build_client_obj(client_uuid, email, password, sub_id, expires_at, user_id)

        await xui.add_client(XUI_HY2_INBOUND, client)

        # DB write after xui — if this fails, the 3x-ui client is orphaned.
        # On next attempt a conflict on email will occur in 3x-ui; the user
        # should contact support. Logged prominently for manual cleanup.
        try:
            upsert_vpn_client(
                user_id, client_uuid, email, sub_id, password, XUI_HY2_INBOUND, expires_at
            )
        except Exception as db_err:
            logger.critical(
                "DB write failed after xui.add_client — orphaned client! "
                "user_id=%s client_uuid=%s email=%s — %s",
                user_id, client_uuid, email, db_err,
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
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 Продлить подписку", callback_data="buy")],
                [InlineKeyboardButton("⬅️ Назад", callback_data="back_main")],
            ]),
        )
        return

    if cdata == "trial":
        if udata["trial_used"]:
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
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 Купить подписку", callback_data="buy")],
                ]),
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

    # Ensure payment row exists even if bot restarted between payment creation and webhook
    save_payment(yoo_id, user_id, plan_key, 0.0)

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
        bot = _app_bot
        if bot:
            await bot.send_message(
                chat_id=user_id,
                text=(
                    f"✅ <b>Оплата прошла! Подписка «{plan_name}» активирована.</b>\n\n"
                    + links_text(sub_id, exp, plan_name)
                ),
                parse_mode="HTML",
            )
        logger.info(
            "webhook: activated plan=%s for user=%s until=%s",
            confirmed_plan, user_id, fmt_dt(exp),
        )
    except Exception as e:
        logger.error("webhook processing error user=%s: %s", user_id, e)

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


asyncio.run(main())
