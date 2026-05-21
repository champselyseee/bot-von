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
        connect_url = f"{config.base_url}/connect/{sub['sub_id']}"
        plan_label = config.plan_label(sub["plan"])

        text = (
            f"📱 <b>Моя подписка</b>\n\n"
            f"Статус: ✅ Активна\n"
            f"Тариф: {plan_label}\n"
            f"До: <b>{exp}</b>\n\n"
            f"📲 <b>Страница подключения</b> (открой в Safari):\n"
            f"<a href='{connect_url}'>{connect_url}</a>"
        )
        await callback.message.edit_text(
            text,
            reply_markup=profile_keyboard(True),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    await callback.answer()
