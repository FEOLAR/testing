from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.filters import ChatMemberUpdatedFilter, KICKED, MEMBER
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message
from sqlalchemy import func, select

from .. import keyboards as kb, texts, ui
from ..config import settings
from ..emoji import e
from ..db import Session, User
from ..remnawave import panel
from ..services import RevokeError, activate_trial, reward_referral_trial, get_or_create_user, refresh_from_panel, revoke_link
from .engage import gated, send_gate

router = Router()
log = logging.getLogger(__name__)


def is_active(user: User) -> bool:
    return bool(user.expire_at and user.expire_at > datetime.now(timezone.utc))


async def load_user(tg) -> User:
    user, _ = await get_or_create_user(tg.id, tg.username, tg.first_name)
    return user


@router.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=KICKED))
async def bot_blocked(event: ChatMemberUpdated):
    """Пользователь заблокировал бота — Telegram сообщает сразу."""
    if event.chat.type == "private":
        from ..services import mark_blocked
        await mark_blocked(event.chat.id)


@router.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=MEMBER))
async def bot_unblocked(event: ChatMemberUpdated):
    if event.chat.type == "private":
        from ..services import mark_blocked
        await mark_blocked(event.chat.id, blocked=False)


def source_tag(arg: str) -> str | None:
    """?start=src_techno → "techno". Другие параметры (кроме ref_) тоже считаем меткой, если они «чистые»."""
    import re
    tag = arg[4:] if arg.startswith("src_") else arg
    tag = tag.lower()[:32]
    return tag if re.fullmatch(r"[a-z0-9_-]{1,32}", tag) else None


@router.message(CommandStart())
async def start(message: Message, command: CommandObject, state: FSMContext):
    await state.clear()
    ref, source = None, None
    if command.args and command.args.startswith("ref_") and command.args[4:].isdigit():
        ref = int(command.args[4:])
    elif command.args:
        source = source_tag(command.args)
    user, _ = await get_or_create_user(message.from_user.id, message.from_user.username,
                                       message.from_user.first_name, referrer_id=ref, source=source)
    if gated(user):  # КПП: сначала подписка на канал, меню — после проверки
        return await send_gate(message, message.from_user.first_name)
    await message.answer(texts.menu_hint(), reply_markup=kb.reply_menu())  # постоянная кнопка «Меню» внизу
    await ui.send_welcome(message, texts.welcome(message.from_user.first_name),
                          kb.main_menu(show_trial=not user.trial_used, show_channel=not (user.channel_bonus or user.trial_used)))


@router.message(Command("menu"))
@router.message(F.text.in_({kb.MENU_TEXT, "Меню", "меню"}))
async def menu_cmd(message: Message, state: FSMContext):
    await state.clear()
    user = await load_user(message.from_user)
    if gated(user):
        return await send_gate(message, message.from_user.first_name)
    await ui.send_welcome(message, texts.welcome(message.from_user.first_name),
                          kb.main_menu(show_trial=not user.trial_used, show_channel=not (user.channel_bonus or user.trial_used)))


@router.message(Command("app"))
async def app_cmd(message: Message, state: FSMContext):
    if not settings.miniapp_url:
        return await menu_cmd(message, state)
    await message.answer("Нажми кнопку, чтобы открыть приложение:", reply_markup=kb.open_app())


@router.callback_query(F.data == "menu")
async def menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await load_user(cb.from_user)
    if gated(user):
        await ui.show(cb, texts.channel_gate(cb.from_user.first_name), reply_markup=kb.channel(gate=True), photo="channel")
        return await cb.answer()
    await ui.show_welcome(cb, texts.welcome(cb.from_user.first_name),
                          kb.main_menu(show_trial=not user.trial_used, show_channel=not (user.channel_bonus or user.trial_used)))
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
    try:
        from ..tv import count_devices
        tv_count = await count_devices(user.tg_id)
    except Exception:
        log.exception("tv devices count failed")
        tv_count = 0
    await ui.show(cb, texts.profile(user, active, tv_count), reply_markup=kb.profile(active, tv_count), photo="profile")
    await cb.answer()


@router.callback_query(F.data == "howto")
async def howto(cb: CallbackQuery):
    await ui.show(cb, texts.howto(), reply_markup=kb.howto(), photo="howto", disable_web_page_preview=True)
    await cb.answer()


@router.callback_query(F.data == "about")
async def about(cb: CallbackQuery):
    await ui.show(cb, texts.about(), reply_markup=kb.back(), photo="features")
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
        return await cb.message.answer(f"{e('no')} Не получилось создать подписку. Попробуй через минуту.")
    if user is None:
        return await cb.message.answer("Пробный период уже использован.")
    user = await reward_referral_trial(cb.bot, cb.from_user.id) or user
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
    await cb.answer("Устройства сброшены. Подключись заново на нужных устройствах." if ok
                    else "Не получилось, попробуй позже.", show_alert=True)


@router.callback_query(F.data == "revoke")
async def revoke(cb: CallbackQuery):
    user = await load_user(cb.from_user)
    if not is_active(user):
        return await cb.answer("Заменить ссылку можно при активной подписке.", show_alert=True)
    await ui.show(cb, texts.revoke_ask(), reply_markup=kb.revoke_confirm(), photo="profile")
    await cb.answer()


@router.callback_query(F.data == "revoke_do")
async def revoke_do(cb: CallbackQuery):
    try:
        user = await revoke_link(cb.from_user.id)
    except RevokeError as err:
        return await cb.answer(str(err), show_alert=True)
    except Exception:
        log.exception("revoke failed")
        return await cb.answer("Не получилось заменить ссылку, попробуй позже или напиши в поддержку.",
                               show_alert=True)
    await ui.show(cb, texts.revoke_done(user), reply_markup=kb.revoke_done(), photo="profile")
    await cb.answer("Готово, ссылка заменена")
