from __future__ import annotations
import secrets
import time
import logging
from urllib.parse import quote

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.filters import Command

import db
from keyboards import plan_keyboard, payment_keyboard, back_to_menu

router = Router()
log = logging.getLogger(__name__)

_BOT_USERNAME: str | None = None  # cached after first call


async def _bot_username(bot) -> str:
    global _BOT_USERNAME
    if not _BOT_USERNAME:
        me = await bot.get_me()
        _BOT_USERNAME = me.username
    return _BOT_USERNAME


def _sub_url(config, sub_id: str) -> str:
    return f"{config.sub_base_url}/sub/{sub_id}"


def _connect_url(config, sub_id: str) -> str:
    return f"{config.base_url}/connect/{sub_id}"


# ─── Entry point: "Купить VPN" ────────────────────────────────────────────────

@router.callback_query(F.data == "buy")
async def cb_buy(callback: CallbackQuery, config, **_):
    text = (
        "💳 <b>Выбери тариф</b>\n\n"
        f"⚡ <b>2 недели</b> — {config.price_2w} ₽\n"
        f"🔥 <b>1 месяц</b> — {config.price_1m} ₽\n\n"
        "Оба тарифа дают доступ к двум протоколам и серверу в Швеции."
    )
    await callback.message.edit_text(
        text,
        reply_markup=plan_keyboard(config.price_2w, config.price_1m),
        parse_mode="HTML",
    )
    await callback.answer()


# ─── Plan selected → create payment ──────────────────────────────────────────

@router.callback_query(F.data.startswith("plan:"))
async def cb_plan(callback: CallbackQuery, config, payments, **_):
    plan = callback.data.split(":", 1)[1]
    if plan not in ("2w", "1m"):  # guard against unexpected callback data
        await callback.answer()
        return
    tg_id = callback.from_user.id
    amount = config.plan_price(plan)
    label = config.plan_label(plan)

    # Ensure user exists
    user_id = await db.upsert_user(
        config.db_path,
        tg_id=tg_id,
        username=callback.from_user.username,
        full_name=callback.from_user.full_name,
    )

    # Check for pending payment
    pending = await db.get_pending_payment(config.db_path, user_id)
    if pending:
        await callback.answer("⚠️ У тебя уже есть незавершённый платёж", show_alert=True)
        return

    if not payments.enabled:
        # Dev mode: auto-provision without real payment
        await callback.answer("⚠️ Платёжная система не настроена (DEV)", show_alert=True)
        return

    # Create YooKassa payment
    await callback.message.edit_text("⏳ Создаю счёт...", parse_mode="HTML")
    try:
        payment_id, pay_url = await payments.create_payment(
            amount=amount,
            description=f"Camille VPN — {label}",
            return_url=f"https://t.me/{await _bot_username(callback.bot)}",
            metadata={"tg_id": tg_id, "plan": plan, "user_id": user_id},
        )
    except Exception as e:
        log.exception("YooKassa create_payment failed: %s", e)
        await callback.message.edit_text(
            "❌ Не удалось создать счёт. Попробуй позже.",
            reply_markup=back_to_menu(),
            parse_mode="HTML",
        )
        return

    await db.create_payment(config.db_path, user_id, payment_id, amount, plan)

    text = (
        f"💳 <b>Оплата Camille VPN — {label}</b>\n\n"
        f"Сумма: <b>{amount} ₽</b>\n\n"
        "Нажми кнопку ниже для оплаты. После успешной оплаты "
        "бот автоматически выдаст тебе доступ."
    )
    await callback.message.edit_text(
        text,
        reply_markup=payment_keyboard(pay_url),
        parse_mode="HTML",
    )


# ─── Cancel payment ───────────────────────────────────────────────────────────

@router.callback_query(F.data == "cancel_payment")
async def cb_cancel(callback: CallbackQuery, config, **_):
    user = await db.get_user_by_tg(config.db_path, callback.from_user.id)
    if user:
        pending = await db.get_pending_payment(config.db_path, user["id"])
        if pending:
            await db.set_payment_status(config.db_path, pending["yookassa_id"], "cancelled")
    await callback.message.edit_text(
        "❌ Платёж отменён.",
        reply_markup=back_to_menu(),
        parse_mode="HTML",
    )
    await callback.answer()


# ─── Admin: manual provision ─/give <tg_id> <plan>───────────────────────────

@router.message(Command("give"))
async def cmd_give(message: Message, config, vpn, **_):
    if message.from_user.id not in config.admin_ids:
        return
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("Usage: /give <tg_id> <2w|1m>")
        return
    try:
        target_tg = int(parts[1])
        plan = parts[2]
        assert plan in ("2w", "1m")
    except Exception:
        await message.answer("Usage: /give <tg_id> <2w|1m>")
        return

    user = await db.get_user_by_tg(config.db_path, target_tg)
    if not user:
        await message.answer("Пользователь не найден")
        return

    await provision_after_payment(
        config, vpn, message.bot, target_tg, user["id"], plan,
        f"manual_{target_tg}_{int(time.time())}",
    )
    await message.answer(f"✅ Подписка выдана пользователю {target_tg}")


# ─── Core provisioning logic (called from webhook too) ───────────────────────

async def provision_after_payment(config, vpn, bot, tg_id: int, user_id: int, plan: str, yookassa_id: str):
    """Called after payment confirmed. Creates VPN user, notifies Telegram user."""

    # Check if user already has an active subscription (renewal)
    existing = await db.get_active_sub(config.db_path, user_id)

    if existing:
        # Renewal: extend existing subscription
        sub_id = existing["sub_id"]
        email = existing["email"]
        now = max(int(time.time()), existing["expires_at"])
        new_expires = now + config.plan_days(plan) * 86400

        ok = await vpn.update_client(email, new_expires)
        if not ok:
            log.error("VPN update_client failed for %s", email)

        await db.extend_sub(config.db_path, sub_id, new_expires, plan)
        await db.set_payment_status(config.db_path, yookassa_id, "succeeded", sub_id)

        from datetime import datetime
        exp_str = datetime.fromtimestamp(new_expires).strftime("%d.%m.%Y")
        connect_url = _connect_url(config, sub_id)

        try:
            await bot.send_message(
                tg_id,
                f"✅ <b>Подписка продлена!</b>\n\n"
                f"Тариф: {config.plan_label(plan)}\n"
                f"Активна до: <b>{exp_str}</b>\n\n"
                f"📲 <a href='{connect_url}'>Инструкция по подключению</a>",
                parse_mode="HTML",
            )
        except Exception as e:
            log.warning("Cannot notify user %s: %s", tg_id, e)
    else:
        # New subscription — check capacity first
        if await db.count_active_subs(config.db_path) >= config.max_active_subs:
            log.warning("Capacity limit reached, cannot provision tg_id=%s", tg_id)
            try:
                await bot.send_message(
                    tg_id,
                    "😔 Оплата прошла, но сейчас все места заняты.\n"
                    "Напиши в поддержку — вернём деньги или добавим вручную: @champselyseee",
                )
            except Exception:
                pass
            # Don't mark payment succeeded — leave as processing so admin can handle manually
            await db.set_payment_status(config.db_path, yookassa_id, "pending")
            return

        sub_id = secrets.token_hex(8)
        email = f"tg{tg_id}"
        password = secrets.token_urlsafe(20)
        expires_at = int(time.time()) + config.plan_days(plan) * 86400

        ok = await vpn.add_client(email, password, sub_id, expires_at)
        if not ok:
            log.error("VPN add_client failed for %s", email)
            try:
                await bot.send_message(
                    tg_id,
                    "❌ Оплата прошла, но не удалось создать VPN-пользователя. "
                    "Напишите в поддержку — исправим вручную.",
                )
            except Exception:
                pass
            return

        inserted = await db.create_sub(config.db_path, user_id, sub_id, email, plan, expires_at, password)
        if not inserted:
            # Email already in DB (expired/cancelled trial) — reactivate that row with new sub_id
            log.info("Reactivating old sub for email=%s tg_id=%s", email, tg_id)
            await db.reactivate_sub(config.db_path, email, sub_id, plan, expires_at, password)
        await db.set_payment_status(config.db_path, yookassa_id, "succeeded", sub_id)

        from datetime import datetime
        exp_str = datetime.fromtimestamp(expires_at).strftime("%d.%m.%Y")
        connect_url = _connect_url(config, sub_id)

        try:
            await bot.send_message(
                tg_id,
                f"🎉 <b>Доступ к Camille VPN открыт!</b>\n\n"
                f"Тариф: {config.plan_label(plan)}\n"
                f"Активна до: <b>{exp_str}</b>\n\n"
                f"📲 <a href='{connect_url}'>Инструкция по подключению</a>\n\n"
                f"<i>Ссылка ведёт на страницу с кнопкой «Добавить в Happ».\n"
                f"Открой её в Safari (не в браузере Telegram).</i>",
                parse_mode="HTML",
            )
        except Exception as e:
            log.warning("Cannot notify user %s: %s", tg_id, e)
