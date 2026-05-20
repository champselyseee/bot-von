from __future__ import annotations
from datetime import datetime

from aiogram import Router, F
from aiogram.types import CallbackQuery

import db
from keyboards import profile_keyboard, back_to_menu

router = Router()


@router.callback_query(F.data == "profile")
async def cb_profile(callback: CallbackQuery, config, **_):
    user = await db.get_user_by_tg(config.db_path, callback.from_user.id)
    if not user:
        await callback.message.edit_text(
            "У тебя ещё нет аккаунта. Нажми /start",
            reply_markup=back_to_menu(),
        )
        await callback.answer()
        return

    sub = await db.get_active_sub(config.db_path, user["id"])

    if not sub:
        text = (
            "📱 <b>Моя подписка</b>\n\n"
            "У тебя нет активной подписки.\n"
            "Нажми «Купить VPN» чтобы начать."
        )
        await callback.message.edit_text(
            text, reply_markup=profile_keyboard(False), parse_mode="HTML"
        )
    else:
        exp = datetime.fromtimestamp(sub["expires_at"]).strftime("%d.%m.%Y")
        sub_url = f"{config.sub_base_url}/sub/{sub['sub_id']}"
        connect_url = f"{config.base_url}/connect/{sub['sub_id']}"
        plan_label = config.plan_label(sub["plan"])

        text = (
            f"📱 <b>Моя подписка</b>\n\n"
            f"Статус: ✅ Активна\n"
            f"Тариф: {plan_label}\n"
            f"До: <b>{exp}</b>\n\n"
            f"🔗 Ссылка подписки:\n<code>{sub_url}</code>"
        )
        await callback.message.edit_text(
            text, reply_markup=profile_keyboard(True), parse_mode="HTML"
        )

    await callback.answer()


@router.callback_query(F.data == "connect_info")
async def cb_connect_info(callback: CallbackQuery, config, **_):
    user = await db.get_user_by_tg(config.db_path, callback.from_user.id)
    if not user:
        await callback.answer("Нет активной подписки", show_alert=True)
        return

    sub = await db.get_active_sub(config.db_path, user["id"])
    if not sub:
        await callback.answer("Нет активной подписки", show_alert=True)
        return

    connect_url = f"{config.base_url}/connect/{sub['sub_id']}"
    sub_url = f"{config.sub_base_url}/sub/{sub['sub_id']}"

    text = (
        "📲 <b>Как подключиться</b>\n\n"
        f"Открой ссылку в <b>Safari</b> (не в браузере Telegram):\n"
        f"<a href='{connect_url}'>{connect_url}</a>\n\n"
        f"Или добавь подписку вручную:\n<code>{sub_url}</code>\n\n"
        "<i>Страница содержит кнопку «Добавить в Happ» и пошаговую инструкцию.</i>"
    )
    await callback.message.edit_text(
        text, reply_markup=back_to_menu(), parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await callback.answer()
