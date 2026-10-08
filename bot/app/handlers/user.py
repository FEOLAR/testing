from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select

from .. import keyboards as kb, texts, ui
from ..config import settings
from ..db import Session, User
from ..remnawave import panel
from ..services import activate_trial, get_or_create_user, refresh_from_panel

router = Router()
log = logging.getLogger(__name__)


def is_active(user: User) -> bool:
    return bool(user.expire_at and user.expire_at > datetime.now(timezone.utc))


async def load_user(tg) -> User:
    user, _ = await get_or_create_user(tg.id, tg.username, tg.first_name)
    return user


@router.message(CommandStart())
async def start(message: Message, command: CommandObject):
    ref = None
    if command.args and command.args.startswith("ref_") and command.args[4:].isdigit():
        ref = int(command.args[4:])
    user, _ = await get_or_create_user(message.from_user.id, message.from_user.username,
                                       message.from_user.first_name, referrer_id=ref)
    await ui.send_welcome(message, texts.welcome(message.from_user.first_name),
                          kb.main_menu(show_trial=not user.trial_used))


@router.callback_query(F.data == "menu")
async def menu(cb: CallbackQuery):
    user = await load_user(cb.from_user)
    await ui.show_welcome(cb, texts.welcome(cb.from_user.first_name),
                          kb.main_menu(show_trial=not user.trial_used))
    await cb.answer()


@router.callback_query(F.data == "profile")
async def profile(cb: CallbackQuery):
    user = await load_user(cb.from_user)
    if user.expire_at:
        try:
            user = await refresh_from_panel(user)
        except Exception:
            log.exception("panel refresh failed")
    active = is_active(user)
    await ui.show(cb, texts.profile(user, active), reply_markup=kb.profile(active))
    await cb.answer()


@router.callback_query(F.data == "howto")
async def howto(cb: CallbackQuery):
    await ui.show(cb, texts.howto(), reply_markup=kb.howto(), photo="howto", disable_web_page_preview=True)
    await cb.answer()


@router.callback_query(F.data == "about")
async def about(cb: CallbackQuery):
    await ui.show(cb, texts.about(), reply_markup=kb.back())
    await cb.answer()


@router.callback_query(F.data == "service")
async def service(cb: CallbackQuery):
    await ui.show(cb, texts.service(), reply_markup=kb.service(), photo="about")
    await cb.answer()


@router.callback_query(F.data == "support")
async def support(cb: CallbackQuery):
    await ui.show(cb, texts.support(), reply_markup=kb.support(), photo="support")
    await cb.answer()


@router.callback_query(F.data == "appstore_help")
async def appstore_help(cb: CallbackQuery):
    await ui.show(cb, texts.appstore_help(), reply_markup=kb.back("howto"), photo="howto", disable_web_page_preview=True)
    await cb.answer()


@router.callback_query(F.data == "disconnect_help")
async def disconnect_help(cb: CallbackQuery):
    await ui.show(cb, texts.disconnect_help(), reply_markup=kb.back("menu"), photo="howto")
    await cb.answer()


@router.callback_query(F.data == "trial")
async def trial(cb: CallbackQuery):
    user = await load_user(cb.from_user)
    if user.trial_used or settings.trial_days <= 0:
        return await cb.answer("Пробный период уже использован", show_alert=True)
    await cb.answer("Создаю подписку…")
    try:
        user = await activate_trial(cb.from_user.id)
    except Exception:
        log.exception("trial failed")
        return await cb.message.answer("😔 Не получилось создать подписку. Попробуй через минуту.")
    if user is None:
        return await cb.message.answer("Пробный период уже использован.")
    await ui.show(cb, texts.trial_ok(user), reply_markup=kb.profile(True))


@router.callback_query(F.data == "ref")
async def referral(cb: CallbackQuery):
    me = await cb.bot.me()
    link = f"https://t.me/{me.username}?start=ref_{cb.from_user.id}"
    async with Session() as s:
        invited = await s.scalar(select(func.count()).where(User.referrer_id == cb.from_user.id))
        paid = await s.scalar(select(func.count()).where(User.referrer_id == cb.from_user.id,
                                                         User.referral_rewarded.is_(True)))
    await ui.show(cb, texts.referral(link, invited or 0, paid or 0), reply_markup=kb.back(), photo="partner")
    await cb.answer()


@router.callback_query(F.data == "reset_hwid")
async def reset_hwid(cb: CallbackQuery):
    user = await load_user(cb.from_user)
    try:
        ok = await panel.reset_devices(user.panel_username)
    except Exception:
        log.exception("reset hwid failed")
        ok = False
    await cb.answer("✅ Устройства сброшены. Подключись заново на нужных устройствах." if ok
                    else "Не получилось, попробуй позже.", show_alert=True)
