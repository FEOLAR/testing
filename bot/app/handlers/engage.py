"""Вовлечение: бонус за подписку на канал и отзывы.

Канал (CHANNEL_USERNAME): в главном меню кнопка «+3 дня за подписку на канал» — пока бонус не получен.
Бот проверяет подписку через getChatMember — для этого он должен быть администратором канала.

Отзывы: кнопка «Оставить отзыв» в меню → человек пишет одним сообщением (текст, фото, видео, голос) →
бот пересылает его получателям (REVIEW_TO, по умолчанию админам). Раз в REVIEW_REMIND_DAYS дней бот
напоминает оставить отзыв тем, у кого была подписка и кто ещё не оставлял; после отзыва — больше не напоминает.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import or_, select, update

from .. import keyboards as kb, texts, ui
from ..config import settings
from ..db import Session, User
from ..emoji import e
from ..services import get_or_create_user, grant_days, reward_referral_trial, safe_send

router = Router()
log = logging.getLogger(__name__)

MEMBER = {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}


def _active(user: User) -> bool:
    return bool(user.expire_at and user.expire_at > datetime.now(timezone.utc))


# ---------- бонус за подписку на канал / КПП ----------

def gated(user: User) -> bool:
    """Новый человек должен сначала пройти КПП: подписаться на канал. Тех, у кого уже была подписка, не трогаем."""
    return bool(settings.channel_name and settings.channel_gate and not user.channel_bonus
                and user.expire_at is None and not user.trial_used)


async def send_gate(message: Message, name: str | None) -> None:
    await ui.send_screen(message, texts.channel_gate(name), kb.channel(gate=True), "channel")

async def is_subscribed(bot: Bot, user_id: int) -> bool:
    member = await bot.get_chat_member(f"@{settings.channel_name}", user_id)
    if member.status in MEMBER:
        return True
    return member.status == ChatMemberStatus.RESTRICTED and bool(getattr(member, "is_member", False))


async def mark_passed(tg_id: int) -> bool:
    async with Session() as s:
        res = await s.execute(update(User).where(User.tg_id == tg_id, User.channel_bonus.is_(False))
                              .values(channel_bonus=True).returning(User.tg_id))
        await s.commit()
        return res.scalar_one_or_none() is not None


async def claim_channel_bonus(tg_id: int) -> User | None:
    """Выдаёт бонус один раз. Бонус за канал и пробный период — одни и те же бесплатные дни: кто брал пробный
    период, бонус не получает, а получивший бонус больше не видит «Попробовать бесплатно».
    None — если бесплатные дни уже были."""
    async with Session() as s:
        res = await s.execute(update(User).where(User.tg_id == tg_id, User.channel_bonus.is_(False),
                                                 User.trial_used.is_(False))
                              .values(channel_bonus=True, trial_used=True).returning(User.tg_id))
        await s.commit()
        if res.scalar_one_or_none() is None:
            return None
    try:
        return await grant_days(tg_id, settings.channel_bonus_days)
    except Exception:
        async with Session() as s:  # не получилось начислить — пусть попробует ещё раз
            await s.execute(update(User).where(User.tg_id == tg_id).values(channel_bonus=False, trial_used=False))
            await s.commit()
        raise


@router.callback_query(F.data == "channel")
async def channel(cb: CallbackQuery):
    if not settings.channel_name:
        return await cb.answer()
    user, _ = await get_or_create_user(cb.from_user.id, cb.from_user.username, cb.from_user.first_name)
    if user.channel_bonus or user.trial_used:
        return await cb.answer("Бесплатные дни уже получены — спасибо, что ты с нами!", show_alert=True)
    await ui.show(cb, texts.channel_offer(), reply_markup=kb.channel(), photo="channel")
    await cb.answer()


@router.callback_query(F.data == "channel_check")
async def channel_check(cb: CallbackQuery):
    if not settings.channel_name:
        return await cb.answer()
    try:
        ok = await is_subscribed(cb.bot, cb.from_user.id)
    except Exception:
        log.exception("channel check failed — бот администратор канала @%s?", settings.channel_name)
        return await cb.answer("Не получилось проверить подписку. Попробуй через минуту.", show_alert=True)
    if not ok:
        return await cb.answer(texts.channel_not_member(), show_alert=True)
    await cb.answer("Подписка есть — начисляю бонус…")
    try:
        user = await claim_channel_bonus(cb.from_user.id)
    except Exception:
        log.exception("channel bonus grant failed")
        return await cb.message.answer(f"{e('no')} Не получилось начислить бонус. Попробуй через минуту.")
    if user is None:
        return await cb.message.answer("Бесплатные дни уже получены — бонус за канал не суммируется с пробным периодом.")
    user = await reward_referral_trial(cb.bot, cb.from_user.id) or user
    await ui.show(cb, texts.channel_ok(user), reply_markup=kb.profile(True), photo="channel")


@router.callback_query(F.data == "gate_check")
async def gate_check(cb: CallbackQuery):
    """КПП: проверили подписку → начислили бонус → показали главное меню."""
    if not settings.channel_name:
        return await cb.answer()
    try:
        ok = await is_subscribed(cb.bot, cb.from_user.id)
    except Exception:
        log.exception("gate check failed — бот администратор канала @%s?", settings.channel_name)
        return await cb.answer("Не получилось проверить подписку. Попробуй через минуту.", show_alert=True)
    if not ok:
        return await cb.answer(texts.channel_not_member(), show_alert=True)
    if settings.channel_bonus_days > 0:
        try:
            if await claim_channel_bonus(cb.from_user.id):  # None — бонус уже был, просто пускаем в меню
                await reward_referral_trial(cb.bot, cb.from_user.id)
        except Exception:
            log.exception("gate bonus grant failed")
            return await cb.answer("Подписка есть, но не получилось начислить бонус. Нажми «Я подписался» ещё раз "
                                   "через минуту.", show_alert=True)
    else:
        await mark_passed(cb.from_user.id)
    user, _ = await get_or_create_user(cb.from_user.id, cb.from_user.username, cb.from_user.first_name)
    await cb.answer(texts.channel_passed(), show_alert=True)
    await cb.message.answer(texts.menu_hint(), reply_markup=kb.reply_menu())
    await ui.show_welcome(cb, texts.welcome(cb.from_user.first_name),
                          kb.main_menu(show_trial=not user.trial_used, show_channel=False))


# ---------- отзывы ----------

class ReviewInput(StatesGroup):
    text = State()


@router.callback_query(F.data == "review")
async def review(cb: CallbackQuery, state: FSMContext):
    await state.set_state(ReviewInput.text)
    await ui.show(cb, texts.review_ask(), reply_markup=kb.back(), photo="review")
    await cb.answer()


_SKIP = {kb.MENU_TEXT, "Меню", "меню"}


@router.message(ReviewInput.text, ~(F.text.startswith("/") | F.text.in_(_SKIP)))
async def review_received(message: Message, state: FSMContext):
    await state.clear()
    user, _ = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    header = texts.review_admin_header(user, _active(user))
    delivered = 0
    for rid in settings.review_recipients:
        if not await safe_send(message.bot, rid, header):
            continue
        try:
            await message.forward(rid)
        except Exception:
            try:
                await message.copy_to(rid)
            except Exception:
                log.exception("review forward to %s failed", rid)
                continue
        delivered += 1
    if not delivered:
        log.warning("review from %s not delivered to anyone (REVIEW_TO=%r)", user.tg_id, settings.review_to)
    async with Session() as s:
        await s.execute(update(User).where(User.tg_id == user.tg_id).values(review_at=datetime.now(timezone.utc)))
        await s.commit()
    await ui.send_screen(message, texts.review_thanks(), kb.back("menu"), "review")


async def review_reminders(bot: Bot) -> None:
    """Раз в час: напомнить оставить отзыв тем, у кого была подписка (за последние 30 дней), кто зарегистрирован
    больше REVIEW_FIRST_DAYS дней назад, ещё не оставлял отзыв и кому не напоминали REVIEW_REMIND_DAYS дней."""
    if settings.review_remind_days <= 0:
        return
    now = datetime.now(timezone.utc)
    async with Session() as s:
        users = (await s.execute(
            select(User).where(
                User.review_at.is_(None),
                User.is_blocked.is_(False),
                User.expire_at.is_not(None),
                User.expire_at > now - timedelta(days=30),
                User.created_at < now - timedelta(days=settings.review_first_days),
                or_(User.review_reminded_at.is_(None),
                    User.review_reminded_at < now - timedelta(days=settings.review_remind_days)),
            ).limit(500)
        )).scalars().all()
    for user in users:
        blocked = False
        try:
            await ui.push_screen(bot, user.tg_id, texts.review_reminder(), kb.review_reminder(), "review")
        except TelegramForbiddenError:
            blocked = True
        except Exception as err:
            log.info("review reminder to %s failed: %s", user.tg_id, err)
            blocked = "chat not found" in str(err).lower()
        async with Session() as s:
            values = {"review_reminded_at": now}
            if blocked:
                values["is_blocked"] = True
            await s.execute(update(User).where(User.tg_id == user.tg_id).values(**values))
            await s.commit()
        await asyncio.sleep(0.05)
