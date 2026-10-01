import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, ErrorEvent

from .config import settings
from .cryptopay import crypto
from .db import init_db
from .handlers import admin, payments, user
from .remnawave import panel
from .scheduler import setup_scheduler
from .webapp import start_webapp

log = logging.getLogger("bot")


def make_storage():
    if settings.redis_url:
        from aiogram.fsm.storage.redis import RedisStorage
        return RedisStorage.from_url(settings.redis_url)
    return MemoryStorage()


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    await init_db()

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=make_storage())
    dp.include_routers(admin.router, payments.router, user.router)

    @dp.errors()
    async def on_error(event: ErrorEvent):
        if isinstance(event.exception, TelegramBadRequest) and "not modified" in str(event.exception):
            return True  # пользователь нажал ту же кнопку дважды
        log.exception("update error", exc_info=event.exception)
        cb = event.update.callback_query
        if cb:
            try:
                await cb.answer("Что-то пошло не так, попробуй ещё раз", show_alert=True)
            except Exception:
                pass
        return True

    await bot.set_my_commands([BotCommand(command="start", description="Главное меню")])

    sched = setup_scheduler(bot)
    sched.start()
    web_runner = await start_webapp(bot)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        sched.shutdown(wait=False)
        await web_runner.cleanup()
        await panel.close()
        await crypto.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
