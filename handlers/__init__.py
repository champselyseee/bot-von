from aiogram import Dispatcher
from .start import router as start_router
from .buy import router as buy_router
from .profile import router as profile_router
from .admin import router as admin_router


def register_all(dp: Dispatcher) -> None:
    dp.include_router(start_router)
    dp.include_router(buy_router)
    dp.include_router(profile_router)
    dp.include_router(admin_router)
