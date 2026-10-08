import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, ErrorEvent, MenuButtonCommands

from .config import settings
from . import emoji
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
    bot.session.middleware(emoji.ButtonIconsGuard())  # иконки на кнопках не должны ломать меню
    import aiogram
    log.info("aiogram %s (Bot API %s)", aiogram.__version__, aiogram.__api_version__)
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

    # Кнопка «Меню» слева от поля ввода — список команд (запуск, главное меню, мини-апп)
    commands = [BotCommand(command="start", description="Запустить бота"),
                BotCommand(command="menu", description="Главное меню")]
    if settings.miniapp_url:
        commands.append(BotCommand(command="app", description="Открыть приложение"))
    await bot.set_my_commands(commands)
    try:
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    except Exception:
        log.warning("cannot set menu button", exc_info=True)
    emoji_task = asyncio.create_task(emoji.setup(bot))  # фирменные эмодзи грузятся в фоне, не задерживая старт

    sched = setup_scheduler(bot)
    sched.start()
    web_runner = await start_webapp(bot)
    polling = [dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())]
    legacy_bot = None
    if settings.legacy_bot_token:
        from .legacy import build_legacy_dispatcher
        legacy_bot = Bot(settings.legacy_bot_token)
        legacy_dp = build_legacy_dispatcher((await bot.me()).username)
        polling.append(legacy_dp.start_polling(legacy_bot, handle_signals=False))
        log.info("legacy bot @%s redirects to the new one", (await legacy_bot.me()).username)
    try:
        await asyncio.gather(*polling)
    finally:
        sched.shutdown(wait=False)
        await web_runner.cleanup()
        await panel.close()
        await crypto.close()
        await bot.session.close()
        if legacy_bot:
            await legacy_bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
