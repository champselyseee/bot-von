from __future__ import annotations
from datetime import datetime

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

import db
from keyboards import admin_keyboard, back_to_menu

router = Router()


def _is_admin(user_id: int, config) -> bool:
    return user_id in config.admin_ids


@router.message(Command("admin"))
async def cmd_admin(message: Message, config, **_):
    if not _is_admin(message.from_user.id, config):
        return
    stats = await db.get_stats(config.db_path)
    text = (
        "👑 <b>Панель администратора</b>\n\n"
        f"👥 Пользователей: {stats['users']}\n"
        f"✅ Активных подписок: {stats['active_subs']}\n"
        f"💰 Выручка: {stats['revenue']} ₽"
    )
    await message.answer(text, reply_markup=admin_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "admin:users")
async def cb_users(callback: CallbackQuery, config, **_):
    if not _is_admin(callback.from_user.id, config):
        await callback.answer("Нет доступа", show_alert=True)
        return

    users = await db.get_all_users_with_subs(config.db_path)
    if not users:
        await callback.message.edit_text("Пользователей нет.", reply_markup=back_to_menu())
        await callback.answer()
        return

    lines = []
    for u in users:
        name = u["username"] and f"@{u['username']}" or u["full_name"] or str(u["tg_id"])
        if u["sub_status"] == "active" and u["expires_at"]:
            exp = datetime.fromtimestamp(u["expires_at"]).strftime("%d.%m")
            lines.append(f"• {name} ✅ до {exp} ({u['plan']})")
        else:
            lines.append(f"• {name} ○ нет подписки")

    text = "👥 <b>Пользователи (последние 50)</b>\n\n" + "\n".join(lines)
    await callback.message.edit_text(text, reply_markup=back_to_menu(), parse_mode="HTML")
    await callback.answer()


@router.message(Command("stats"))
async def cmd_stats(message: Message, config, **_):
    if not _is_admin(message.from_user.id, config):
        return
    stats = await db.get_stats(config.db_path)
    await message.answer(
        f"👥 {stats['users']} | ✅ {stats['active_subs']} | 💰 {stats['revenue']} ₽"
    )


@router.message(Command("revoke"))
async def cmd_revoke(message: Message, config, vpn, **_):
    """Usage: /revoke <tg_id>  — remove user's VPN access immediately."""
    if not _is_admin(message.from_user.id, config):
        return
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Usage: /revoke <tg_id>")
        return
    try:
        target_tg = int(parts[1])
    except ValueError:
        await message.answer("tg_id должен быть числом")
        return

    user = await db.get_user_by_tg(config.db_path, target_tg)
    if not user:
        await message.answer("Пользователь не найден")
        return

    sub = await db.get_active_sub(config.db_path, user["id"])
    if not sub:
        await message.answer("Нет активной подписки")
        return

    ok = await vpn.remove_client(sub["email"], sub["sub_id"])
    await db.set_sub_status(config.db_path, sub["sub_id"], "cancelled")
    await message.answer(
        f"{'✅' if ok else '⚠️'} Подписка отозвана (VPN API: {'OK' if ok else 'FAIL'})"
    )
