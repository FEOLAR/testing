"""Рассылка о переезде через СТАРОГО бота — запуск из консоли сервера.

    docker exec -it vpn-bot python -m app.broadcast_old test   # только админам (проверка)
    docker exec -it vpn-bot python -m app.broadcast_old all    # всем пользователям из базы

Свой текст (HTML) можно положить в /app/broadcast.txt — иначе берётся текст по умолчанию.
Всё, что происходит, печатается в консоль: какие боты, сколько людей, какие ошибки.
"""
from __future__ import annotations

import asyncio
import sys
from collections import Counter
from pathlib import Path

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from .config import settings
from .db import Session, User

DEFAULT_TEXT = (
    "🚀 <b>Мы переехали и обновились — теперь мы {brand}!</b>\n\n"
    "Ваша подписка, срок и VPN работают как раньше — <b>ничего переподключать не нужно</b>.\n\n"
    "Продление, оплата, поддержка и новое приложение теперь в новом боте 👇"
)


async def main(mode: str) -> None:
    if mode not in ("test", "all"):
        print(__doc__)
        return
    if not settings.legacy_bot_token:
        print("❌ В .env не задан LEGACY_BOT_TOKEN")
        return
    if settings.legacy_bot_token == settings.bot_token:
        print("❌ LEGACY_BOT_TOKEN совпадает с BOT_TOKEN — в LEGACY_BOT_TOKEN должен быть токен СТАРОГО бота")
        return

    props = DefaultBotProperties(parse_mode=ParseMode.HTML)
    new, old = Bot(settings.bot_token, default=props), Bot(settings.legacy_bot_token, default=props)
    try:
        new_me, old_me = await new.me(), await old.me()
        print(f"Старый бот: @{old_me.username}  →  новый бот: @{new_me.username}")

        custom = Path(__file__).resolve().parent.parent / "broadcast.txt"
        text = custom.read_text(encoding="utf-8").strip() if custom.exists() else \
            DEFAULT_TEXT.format(brand=settings.brand_name)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text="➡️ Открыть нового бота", url=f"https://t.me/{new_me.username}")]])

        if mode == "test":
            ids = sorted(settings.admins)
        else:
            async with Session() as s:
                ids = list((await s.execute(select(User.tg_id))).scalars().all())
        print(f"Получателей: {len(ids)} ({'только админы' if mode == 'test' else 'все из базы'})\n--- текст ---\n{text}\n-------------")

        ok, errors = 0, Counter()
        for n, tg_id in enumerate(ids, 1):
            for _ in range(3):
                try:
                    await old.send_message(tg_id, text, reply_markup=kb)
                    ok += 1
                    break
                except TelegramRetryAfter as e:
                    await asyncio.sleep(e.retry_after + 1)
                except Exception as e:
                    errors[f"{type(e).__name__}: {str(e)[:80]}"] += 1
                    if mode == "test":
                        print(f"  {tg_id}: {type(e).__name__}: {e}")
                    break
            if n % 50 == 0:
                print(f"  …{n}/{len(ids)}")
            await asyncio.sleep(0.05)

        print(f"\n✅ Доставлено: {ok}   ❌ Не доставлено: {sum(errors.values())}")
        for err, cnt in errors.most_common(5):
            print(f"   {cnt} × {err}")
        if mode == "test" and ok == 0:
            print("\nПодсказка: «chat not found» / «bot was blocked» — вы не нажимали «Старт» у СТАРОГО бота "
                  "или заблокировали его. Откройте старого бота, нажмите «Старт» и повторите test.")
    finally:
        await new.session.close()
        await old.session.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else ""))
