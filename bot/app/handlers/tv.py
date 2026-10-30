"""Подключение телевизора (лаунчер WhiteHole) по коду: QR → /start tv_<код>, команда /tv или кнопка
«Подключить ТВ по коду» в «Инструкции». Сама логика кодов — в app/tv.py."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .. import keyboards as kb, texts, ui
from .. import tv
from ..services import get_or_create_user, refresh_from_panel

router = Router()
log = logging.getLogger(__name__)


class TvCodeInput(StatesGroup):
    code = State()


def _active(user) -> bool:
    return bool(user.expire_at and user.expire_at > datetime.now(timezone.utc))


async def _fresh(user):
    if user.expire_at:
        try:
            return await refresh_from_panel(user)
        except Exception:
            log.exception("panel refresh failed")
    return user


async def _ask_screen(message: Message, code: str, user) -> None:
    """Экран «Подключить телевизор?» новым сообщением (после QR или введённого кода)."""
    pair = await tv.get_pairing(code)
    if pair is None or pair.get("st") != "pending":
        await message.answer(f"{texts.e('alert')} Код <code>{code}</code> не найден или устарел. "
                             "На телевизоре появится новый код — попробуй с ним.")
        return
    user = await _fresh(user)
    if not _active(user):
        from .engage import gated, send_gate
        if gated(user):  # новичок: как и при обычном /start — сначала канал (это и есть бесплатные дни)
            await message.answer(texts.tv_no_sub())
            return await send_gate(message, message.from_user.first_name)
        await ui.send_screen(message, texts.tv_no_sub(), kb.tv_no_sub(show_trial=not user.trial_used), "profile")
        return
    await ui.send_screen(message, texts.tv_ask(pair.get("name"), code), kb.tv_confirm(code), "howto")


@router.message(CommandStart(deep_link=True, magic=F.args.regexp(r"^tv_\d{6}$")))
async def start_tv(message: Message, command: CommandObject, state: FSMContext):
    await state.clear()
    user, created = await get_or_create_user(message.from_user.id, message.from_user.username,
                                             message.from_user.first_name, source="tv")
    if created:
        await message.answer(texts.menu_hint(), reply_markup=kb.reply_menu())
    await _ask_screen(message, command.args[3:], user)


@router.message(Command("tv"))
async def tv_cmd(message: Message, command: CommandObject, state: FSMContext):
    user, _ = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    code = tv.parse_code(command.args)
    if code:
        await state.clear()
        return await _ask_screen(message, code, user)
    await state.set_state(TvCodeInput.code)
    await ui.send_screen(message, texts.tv_code_ask(), kb.back("howto"), "howto")


@router.callback_query(F.data == "tv_code")
async def tv_code(cb: CallbackQuery, state: FSMContext):
    await state.set_state(TvCodeInput.code)
    await ui.show(cb, texts.tv_code_ask(), reply_markup=kb.back("howto"), photo="howto",
                  disable_web_page_preview=True)
    await cb.answer()


_SKIP = {kb.MENU_TEXT, "Меню", "меню"}


@router.message(TvCodeInput.code, F.text, ~(F.text.startswith("/") | F.text.in_(_SKIP)))
async def tv_code_received(message: Message, state: FSMContext):
    code = tv.parse_code(message.text)
    if not code:
        return await message.answer(texts.tv_bad_code())
    await state.clear()
    user, _ = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await _ask_screen(message, code, user)


@router.callback_query(F.data.startswith("tv_ok:"))
async def tv_ok(cb: CallbackQuery):
    code = cb.data.split(":", 1)[1]
    user, _ = await get_or_create_user(cb.from_user.id, cb.from_user.username, cb.from_user.first_name)
    user = await _fresh(user)
    if not _active(user) or not user.sub_url:
        await ui.show(cb, texts.tv_no_sub(), reply_markup=kb.tv_no_sub(show_trial=not user.trial_used), photo="profile")
        return await cb.answer()
    try:
        device = await tv.confirm_pairing(code, user.tg_id, user.sub_url)
    except tv.PairError as err:
        return await cb.answer(str(err), show_alert=True)
    except Exception:
        log.exception("tv pairing confirm failed")
        return await cb.answer("Не получилось подключить телевизор, попробуй ещё раз.", show_alert=True)
    log.info("tv paired: user %s device %s (%s)", user.tg_id, device.id, device.name)
    await ui.show(cb, texts.tv_done(device.name), reply_markup=kb.tv_done(), photo="howto")
    await cb.answer("Телевизор подключён")


@router.callback_query(F.data == "tv_no")
async def tv_no(cb: CallbackQuery):
    await ui.show(cb, f"{texts.e('no')} Подключение телевизора отменено.", reply_markup=kb.back("menu"), photo="howto")
    await cb.answer()


@router.callback_query(F.data == "tv_list")
async def tv_list(cb: CallbackQuery):
    devices = await tv.active_devices(cb.from_user.id)
    if not devices:
        await cb.answer("Привязанных телевизоров нет", show_alert=True)
        return
    await ui.show(cb, texts.tv_list(devices), reply_markup=kb.tv_list(devices), photo="profile")
    await cb.answer()


@router.callback_query(F.data.startswith("tv_del:"))
async def tv_del(cb: CallbackQuery):
    try:
        device_id = int(cb.data.split(":", 1)[1])
    except ValueError:
        return await cb.answer()
    ok = await tv.revoke_device(device_id, cb.from_user.id)
    devices = await tv.active_devices(cb.from_user.id)
    await cb.answer("Телевизор отвязан" if ok else "Уже отвязан")
    if devices:
        await ui.show(cb, texts.tv_list(devices), reply_markup=kb.tv_list(devices), photo="profile")
    else:
        await ui.show(cb, f"{texts.e('ok')} Все телевизоры отвязаны.", reply_markup=kb.back("profile"), photo="profile")
