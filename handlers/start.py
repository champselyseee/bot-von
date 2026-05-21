from __future__ import annotations
import secrets
import time
import logging

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from keyboards import main_menu, back_to_menu
import db

router = Router()
log = logging.getLogger(__name__)

_WELCOME = (
    "🔐 <b>Camille VPN</b>\n\n"
    "Сервер в Швеции 🇸🇪 · VLESS+Reality и Hysteria 2\n"
    "Быстро, надёжно, без логов\n\n"
    "Выбери действие:"
)

_HELP = (
    "❓ <b>Помощь</b>\n\n"
    "<b>Что такое Camille VPN?</b>\n"
    "Личный VPN-сервер в Швеции. Два протокола:\n"
    "• <b>Hysteria 2</b> — быстрый, на UDP\n"
    "• <b>VLESS+Reality</b> — маскируется под обычный HTTPS\n\n"
    "<b>Тарифы:</b>\n"
    "• 2 недели — 149 ₽\n"
    "• 1 месяц — 249 ₽\n\n"
    "<b>Приложение:</b> Happ (App Store / Google Play)\n\n"
    "По вопросам: @champselyseee"
)


@router.message(CommandStart())
async def cmd_start(message: Message, config, vpn, **_):
    user_id = await db.upsert_user(
        config.db_path,
        tg_id=message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name,
    )

    # Новый пользователь — даём 1 день бесплатно
    if not await db.has_any_sub(config.db_path, user_id):
        await _give_trial(message, config, vpn, user_id)
        return

    await message.answer(_WELCOME, reply_markup=main_menu(), parse_mode="HTML")


async def _give_trial(message: Message, config, vpn, user_id: int):
    tg_id = message.from_user.id
    waiting = await message.answer("⏳ Активирую пробный доступ...")

    sub_id   = secrets.token_hex(8)
    email    = f"tg{tg_id}"
    password = secrets.token_urlsafe(20)
    expires_at = int(time.time()) + 86400  # 24 часа

    ok = await vpn.add_client(email, password, sub_id, expires_at)

    try:
        await waiting.delete()
    except Exception:
        pass

    if not ok:
        log.error("Trial provision failed for tg_id=%s", tg_id)
        await message.answer(
            _WELCOME + "\n\n⚠️ Не удалось создать пробный доступ. Напишите в поддержку.",
            reply_markup=main_menu(),
            parse_mode="HTML",
        )
        return

    await db.create_sub(config.db_path, user_id, sub_id, email, "1d", expires_at)

    connect_url = f"{config.base_url}/connect/{sub_id}"

    await message.answer(
        "🎁 <b>Добро пожаловать в Camille VPN!</b>\n\n"
        "Тебе активирован <b>бесплатный пробный день</b> — 24 часа 🎉\n\n"
        f"📲 <a href='{connect_url}'>Нажми сюда — открой в Safari и настрой Happ</a>\n\n"
        "<i>На странице три шага: скачать Happ, добавить правила маршрутизации "
        "и подписку. Открывай обязательно в Safari, не в браузере Telegram.</i>",
        reply_markup=main_menu(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.callback_query(F.data == "menu")
async def cb_menu(callback: CallbackQuery, **_):
    await callback.message.edit_text(_WELCOME, reply_markup=main_menu(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "help")
async def cb_help(callback: CallbackQuery, **_):
    await callback.message.edit_text(_HELP, reply_markup=back_to_menu(), parse_mode="HTML")
    await callback.answer()
