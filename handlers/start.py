from __future__ import annotations
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from keyboards import main_menu, back_to_menu
import db

router = Router()

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
    "По вопросам: @camille_vpn_support"
)


@router.message(CommandStart())
async def cmd_start(message: Message, config, **_):
    await db.upsert_user(
        config.db_path,
        tg_id=message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name,
    )
    await message.answer(_WELCOME, reply_markup=main_menu(), parse_mode="HTML")


@router.callback_query(F.data == "menu")
async def cb_menu(callback: CallbackQuery, **_):
    await callback.message.edit_text(_WELCOME, reply_markup=main_menu(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "help")
async def cb_help(callback: CallbackQuery, **_):
    await callback.message.edit_text(_HELP, reply_markup=back_to_menu(), parse_mode="HTML")
    await callback.answer()
