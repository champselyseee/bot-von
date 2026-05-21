from __future__ import annotations
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="💳 Купить VPN", callback_data="buy"))
    kb.row(InlineKeyboardButton(text="📱 Моя подписка", callback_data="profile"))
    kb.row(InlineKeyboardButton(text="❓ Помощь", callback_data="help"))
    return kb.as_markup()


def plan_keyboard(price_2w: int, price_1m: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=f"⚡ 2 недели — {price_2w} ₽", callback_data="plan:2w"))
    kb.row(InlineKeyboardButton(text=f"🔥 1 месяц — {price_1m} ₽", callback_data="plan:1m"))
    kb.row(InlineKeyboardButton(text="◀️ Назад", callback_data="menu"))
    return kb.as_markup()


def payment_keyboard(url: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="💳 Перейти к оплате", url=url))
    kb.row(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_payment"))
    return kb.as_markup()


def profile_keyboard(has_sub: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if has_sub:
        kb.row(InlineKeyboardButton(text="🔄 Продлить подписку", callback_data="buy"))
    else:
        kb.row(InlineKeyboardButton(text="💳 Купить VPN", callback_data="buy"))
    kb.row(InlineKeyboardButton(text="◀️ Назад", callback_data="menu"))
    return kb.as_markup()


def back_to_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu"))
    return kb.as_markup()


def admin_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="👥 Пользователи", callback_data="admin:users"))
    kb.row(InlineKeyboardButton(text="🔍 Найти", callback_data="admin:find"))
    kb.row(InlineKeyboardButton(text="◀️ Назад", callback_data="menu"))
    return kb.as_markup()
