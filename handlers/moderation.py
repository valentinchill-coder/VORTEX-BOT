import re
from html import escape
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Router
from aiogram.enums import ChatMemberStatus
from aiogram.filters import Command
from aiogram.types import Message, ChatPermissions
from aiogram.exceptions import TelegramAPIError

from database.db import Database
from handlers.ranks import rank_denial

router = Router()


async def is_admin(message: Message, bot: Bot, owner_ids: frozenset[int]) -> bool:
    if not message.from_user:
        return False
    if message.from_user.id in owner_ids:
        return True
    if message.chat.type == "private":
        return False
    member = await bot.get_chat_member(message.chat.id, message.from_user.id)
    return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)


async def target_from_reply(message: Message):
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.answer("Используй команду ответом на сообщение пользователя.")
        return None
    target = message.reply_to_message.from_user
    if message.from_user and target.id == message.from_user.id:
        await message.answer("Нельзя применять это действие к самому себе.")
        return None
    if target.is_bot:
        await message.answer("Нельзя применить это действие к боту.")
        return None
    return target


async def check_admin(message: Message, bot: Bot, owner_ids: frozenset[int]) -> bool:
    try:
        allowed = await is_admin(message, bot, owner_ids)
    except TelegramAPIError:
        allowed = False
    if not allowed:
        await message.answer("Эта команда доступна только администраторам.")
    return allowed



async def bot_can_restrict(message: Message, bot: Bot) -> bool:
    """Return whether the bot is an administrator allowed to restrict members."""
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(message.chat.id, me.id)
    except TelegramAPIError as exc:
        await message.answer(f"Не удалось проверить права бота: {exc.message}")
        return False
    if member.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR):
        await message.answer("У бота нет прав администратора. Назначь VORTEX BOT администратором группы.")
        return False
    if member.status != ChatMemberStatus.CREATOR and not getattr(member, "can_restrict_members", False):
        await message.answer("У бота нет права «Блокировка участников». Включи его в настройках администраторов группы.")
        return False
    return True


async def target_is_restrictable(message: Message, bot: Bot, target) -> bool:
    """Telegram admins/creator cannot be muted, kicked or banned by the bot."""
    try:
        member = await bot.get_chat_member(message.chat.id, target.id)
    except TelegramAPIError as exc:
        await message.answer(f"Не удалось проверить участника: {exc.message}")
        return False
    if member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR):
        await message.answer("Нельзя ограничить, исключить или заблокировать администратора группы.")
        return False
    return True


@router.message(Command("warn"))
async def warn(message: Message, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not await rank_denial(message, db, bot, owner_ids, "warn"):
        return
    target = await target_from_reply(message)
    if not target:
        return
    reason = (message.text or "").partition(" ")[2].strip() or "Причина не указана"
    count = await db.add_warning(message.chat.id, target.id, message.from_user.id, reason)
    await db.log_event(message.chat.id, "warn")
    await db.log_moderation_action(message.chat.id, message.from_user.id, target.id, "warn", reason)
    await message.answer(f"⚠️ {escape(target.full_name)}: предупреждение {count}. Причина: {escape(reason)}")


@router.message(Command("warnings"))
async def warnings(message: Message, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not await rank_denial(message, db, bot, owner_ids, "warnings"):
        return
    target = await target_from_reply(message)
    if target:
        count = await db.warning_count(message.chat.id, target.id)
        await message.answer(f"У {escape(target.full_name)} предупреждений: {count}.")


@router.message(Command("clearwarns"))
async def clearwarns(message: Message, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not await rank_denial(message, db, bot, owner_ids, "clearwarns"):
        return
    target = await target_from_reply(message)
    if target:
        await db.clear_warnings(message.chat.id, target.id)
        await db.log_moderation_action(message.chat.id, message.from_user.id, target.id, "clear_warnings")
        await message.answer(f"Предупреждения пользователя {escape(target.full_name)} очищены.")


def parse_duration(value: str) -> timedelta | None:
    match = re.fullmatch(r"(\d+)([mhd])", value.lower())
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    if amount < 1:
        return None
    seconds = amount * {"m": 60, "h": 3600, "d": 86400}[unit]
    if seconds > 366 * 86400:
        return None
    return timedelta(seconds=seconds)


@router.message(Command("mute"))
async def mute(message: Message, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not await rank_denial(message, db, bot, owner_ids, "mute"):
        return
    target = await target_from_reply(message)
    if not target:
        return
    if not await bot_can_restrict(message, bot) or not await target_is_restrictable(message, bot, target):
        return
    parts = (message.text or "").split(maxsplit=1)
    duration = parse_duration(parts[1].strip()) if len(parts) > 1 else timedelta(minutes=10)
    if not duration:
        await message.answer("Формат времени: 10m, 2h или 1d. Максимум — 366d.")
        return
    until = datetime.now(timezone.utc) + duration
    try:
        await bot.restrict_chat_member(
            message.chat.id,
            target.id,
            permissions=ChatPermissions(
                can_send_messages=False,
                can_send_audios=False,
                can_send_documents=False,
                can_send_photos=False,
                can_send_videos=False,
                can_send_video_notes=False,
                can_send_voice_notes=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
                can_manage_topics=False,
            ),
            until_date=until,
        )
        await db.log_moderation_action(message.chat.id, message.from_user.id, target.id, "mute", parts[1] if len(parts) > 1 else "10m")
        await message.answer(f"🔇 {escape(target.full_name)} ограничен на {escape(parts[1]) if len(parts) > 1 else '10m'}.")
    except TelegramAPIError as exc:
        await message.answer(f"Не удалось ограничить пользователя: {exc.message}")


@router.message(Command("unmute"))
async def unmute(message: Message, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not await rank_denial(message, db, bot, owner_ids, "unmute"):
        return
    target = await target_from_reply(message)
    if not target:
        return
    if not await bot_can_restrict(message, bot) or not await target_is_restrictable(message, bot, target):
        return
    try:
        chat = await bot.get_chat(message.chat.id)
        await bot.restrict_chat_member(
            message.chat.id,
            target.id,
            permissions=chat.permissions or ChatPermissions(
                can_send_messages=True,
                can_send_audios=True,
                can_send_documents=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_video_notes=True,
                can_send_voice_notes=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_manage_topics=False,
            ),
        )
        await db.log_moderation_action(message.chat.id, message.from_user.id, target.id, "unmute")
        await message.answer(f"🔊 Ограничения сняты: {escape(target.full_name)}.")
    except TelegramAPIError as exc:
        await message.answer(f"Не удалось снять ограничения: {exc.message}")


@router.message(Command("kick"))
async def kick(message: Message, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not await rank_denial(message, db, bot, owner_ids, "kick"):
        return
    target = await target_from_reply(message)
    if not target:
        return
    if not await bot_can_restrict(message, bot) or not await target_is_restrictable(message, bot, target):
        return
    try:
        await bot.ban_chat_member(message.chat.id, target.id)
        await bot.unban_chat_member(message.chat.id, target.id, only_if_banned=True)
        await db.log_moderation_action(message.chat.id, message.from_user.id, target.id, "kick")
        await message.answer(f"👢 {escape(target.full_name)} удалён из группы.")
    except TelegramAPIError as exc:
        await message.answer(f"Не удалось удалить пользователя: {exc.message}")


@router.message(Command("ban"))
async def ban(message: Message, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not await rank_denial(message, db, bot, owner_ids, "ban"):
        return
    target = await target_from_reply(message)
    if not target:
        return
    try:
        await bot.ban_chat_member(message.chat.id, target.id)
        await db.log_moderation_action(message.chat.id, message.from_user.id, target.id, "ban")
        await message.answer(f"⛔ {escape(target.full_name)} заблокирован.")
    except TelegramAPIError as exc:
        await message.answer(f"Не удалось заблокировать пользователя: {exc.message}")


@router.message(Command("unban"))
async def unban(message: Message, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not await rank_denial(message, db, bot, owner_ids, "unban"):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Укажи Telegram ID: /unban 123456789")
        return
    if not await bot_can_restrict(message, bot):
        return
    try:
        target_id = int(parts[1])
        await bot.unban_chat_member(message.chat.id, target_id, only_if_banned=True)
        await db.log_moderation_action(message.chat.id, message.from_user.id, target_id, "unban")
        await message.answer("Блокировка снята.")
    except TelegramAPIError as exc:
        await message.answer(f"Не удалось разблокировать: {exc.message}")


@router.message(Command("audit"))
async def audit_command(message: Message, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not await rank_denial(message, db, bot, owner_ids, "audit"):
        return
    rows = await db.recent_moderation_actions(message.chat.id, limit=15)
    if not rows:
        await message.answer("📋 Журнал модерации пока пуст.")
        return
    lines = ["📋 <b>Последние действия модерации</b>", ""]
    for row in rows:
        details = f" · {escape(row['details'])}" if row["details"] else ""
        lines.append(
            f"<code>{escape(row['created_at'][:16])}</code> "
            f"<b>{escape(row['action'])}</b> · "
            f"{row['actor_id']} → {row['target_id']}{details}"
        )
    await message.answer("\n".join(lines))
