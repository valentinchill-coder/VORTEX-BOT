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

async def target_from_reply_or_username(message: Message, db: Database, bot: Bot):
    """Resolve a moderation target from a replied-to message or a known group username."""
    if message.reply_to_message and message.reply_to_message.from_user:
        target = message.reply_to_message.from_user
    else:
        parts = (message.text or "").split(maxsplit=1)
        username = parts[1].strip().split()[0] if len(parts) > 1 else ""
        if not re.fullmatch(r"@[a-zA-Z0-9_]{5,32}", username):
            await message.answer("Ответь на сообщение участника или укажи @username: /unmute @username")
            return None
        target_id = await db.find_user_id_by_username(message.chat.id, username)
        if target_id is None:
            await message.answer(
                "Не нашёл однозначного участника по этому username. "
                "Бот должен был видеть пользователя в группе до этого; проверь @username."
            )
            return None
        try:
            member = await bot.get_chat_member(message.chat.id, target_id)
        except TelegramAPIError as exc:
            await message.answer(f"Не удалось проверить участника: {exc.message}")
            return None
        target = member.user
        if (target.username or "").casefold() != username[1:].casefold():
            await message.answer("Username изменился. Укажи актуальный @username.")
            return None

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
    await message.answer(
        f"⚠️ {escape(target.full_name)}: предупреждение {count}. "
        f"Причина: {escape(reason)}\nСрок действия: 30 дней."
    )


@router.message(Command("warnings"))
async def warnings(message: Message, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not await rank_denial(message, db, bot, owner_ids, "warnings"):
        return
    target = await target_from_reply(message)
    if target:
        count = await db.warning_count(message.chat.id, target.id)
        rows = await db.recent_warnings(message.chat.id, target.id, limit=5)
        lines = [
            f"⚠️ <b>Предупреждения: {escape(target.full_name)}</b>",
            f"Всего активных предупреждений: <b>{count}</b>",
        ]
        if rows:
            lines.append("")
            lines.append("<b>Последние предупреждения:</b>")
            for row in rows:
                created = escape(row["created_at"][:16].replace("T", " "))
                reason = escape(row["reason"])
                if row.get("revoked_at"):
                    status = "отменено"
                elif row.get("expires_at") and row["expires_at"] <= datetime.now(timezone.utc).isoformat():
                    status = "истекло"
                else:
                    status = "активно"
                try:
                    moderator = await bot.get_chat_member(message.chat.id, row["admin_id"])
                    moderator_user = moderator.user
                    moderator_label = (
                        f"@{moderator_user.username}"
                        if moderator_user.username
                        else moderator_user.full_name
                    )
                except TelegramAPIError:
                    moderator_label = "профиль недоступен"
                lines.append(
                    f"• <code>{created}</code> — {reason} "
                    f"[{status}] (модератор: {escape(moderator_label)})"
                )
        else:
            lines.append("Нарушений не зафиксировано.")
        await message.answer("\n".join(lines))


@router.message(Command("clearwarns"))
async def clearwarns(message: Message, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not await rank_denial(message, db, bot, owner_ids, "clearwarns"):
        return
    target = await target_from_reply(message)
    if target:
        await db.clear_warnings(message.chat.id, target.id)
        await db.log_moderation_action(message.chat.id, message.from_user.id, target.id, "clear_warnings")
        await message.answer(
            f"Активные предупреждения пользователя {escape(target.full_name)} отменены. "
            "История сохранена в журнале."
        )


def parse_duration(value: str) -> timedelta | None:
    """Parse moderator-selected mute duration: 30m, 2h, 1d, or 1h30m."""
    value = (value or "").strip().lower().replace("ё", "е")
    compact = re.fullmatch(r"(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?", value)
    if compact and any(compact.groups()):
        days, hours, minutes = (int(part or 0) for part in compact.groups())
    else:
        # Also accept readable Russian forms: "1 день 2 часа 30 минут".
        readable = re.fullmatch(
            r"(?:(\d+)\s*(?:д(?:ень|ня|ней|н\.)?))?\s*"
            r"(?:(\d+)\s*(?:ч(?:ас|аса|асов|\.)?))?\s*"
            r"(?:(\d+)\s*(?:м(?:инут(?:а|ы)?|ин\.)?))?",
            value,
        )
        if not readable or not any(readable.groups()):
            return None
        days, hours, minutes = (int(part or 0) for part in readable.groups())
    seconds = days * 86400 + hours * 3600 + minutes * 60
    if seconds < 60 or seconds > 366 * 86400:
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
    duration_text = parts[1].strip() if len(parts) > 1 else ""
    duration = parse_duration(duration_text)
    if not duration:
        await message.answer(
            "Модератор должен указать срок мута: /mute 30m, /mute 2h, /mute 1d или /mute 1h30m. "
            "Можно словами: /mute 30 минут, /mute 2 часа. Минимум — 1 минута, максимум — 366 дней."
        )
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
        await db.log_moderation_action(message.chat.id, message.from_user.id, target.id, "mute", duration_text)
        await message.answer(f"🔇 {escape(target.full_name)} ограничен на {escape(duration_text)}.")
    except TelegramAPIError as exc:
        await message.answer(f"Не удалось ограничить пользователя: {exc.message}")


@router.message(Command("unmute"))
async def unmute(message: Message, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not await rank_denial(message, db, bot, owner_ids, "unmute"):
        return
    target = await target_from_reply_or_username(message, db, bot)
    if not target:
        return
    if not await bot_can_restrict(message, bot) or not await target_is_restrictable(message, bot, target):
        return
    try:
        # Restore the group's actual default permissions rather than granting
        # every permission unconditionally. This reliably removes the member-
        # specific restriction while respecting the group's current settings.
        chat = await bot.get_chat(message.chat.id)
        permissions = chat.permissions or ChatPermissions(
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
        )
        await bot.restrict_chat_member(
            message.chat.id,
            target.id,
            permissions=permissions,
            use_independent_chat_permissions=False,
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
    parts = (message.text or "").split(maxsplit=1)
    reason = parts[1].strip()[:500] if len(parts) > 1 else "Причина не указана"
    try:
        await bot.ban_chat_member(message.chat.id, target.id)
        await bot.unban_chat_member(message.chat.id, target.id, only_if_banned=True)
        await db.log_moderation_action(message.chat.id, message.from_user.id, target.id, "kick", reason)
        await message.answer(f"👢 {escape(target.full_name)} удалён из группы. Причина: {escape(reason)}")
    except TelegramAPIError as exc:
        await message.answer(f"Не удалось удалить пользователя: {exc.message}")


@router.message(Command("ban"))
async def ban(message: Message, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not await rank_denial(message, db, bot, owner_ids, "ban"):
        return
    target = await target_from_reply(message)
    if not target:
        return
    if not await bot_can_restrict(message, bot) or not await target_is_restrictable(message, bot, target):
        return
    parts = (message.text or "").split(maxsplit=1)
    reason = parts[1].strip()[:500] if len(parts) > 1 else "Причина не указана"
    try:
        await bot.ban_chat_member(message.chat.id, target.id)
        await db.log_moderation_action(message.chat.id, message.from_user.id, target.id, "ban", reason)
        await message.answer(f"⛔ {escape(target.full_name)} заблокирован. Причина: {escape(reason)}")
    except TelegramAPIError as exc:
        await message.answer(f"Не удалось заблокировать пользователя: {exc.message}")


@router.message(Command("unban"))
async def unban(message: Message, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not await rank_denial(message, db, bot, owner_ids, "unban"):
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 2 or not parts[1].startswith("@"):
        await message.answer("Укажи username: /unban @username [причина]")
        return
    reason = parts[2].strip()[:500] if len(parts) > 2 else "Причина не указана"
    target_id = await db.find_user_id_by_username(message.chat.id, parts[1])
    if target_id is None:
        await message.answer(
            "Не нашёл однозначного участника по этому username. "
            "Бот должен был видеть пользователя в группе до блокировки; проверь @username."
        )
        return
    if not await bot_can_restrict(message, bot):
        return
    try:
        await bot.unban_chat_member(message.chat.id, target_id, only_if_banned=True)
        await db.log_moderation_action(message.chat.id, message.from_user.id, target_id, "unban", reason)
        await message.answer(f"Блокировка пользователя {escape(parts[1])} снята. Причина: {escape(reason)}")
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
    user_labels: dict[int, str] = {}

    async def display_user(user_id: int) -> str:
        if user_id not in user_labels:
            try:
                member = await bot.get_chat_member(message.chat.id, user_id)
                user = member.user
                user_labels[user_id] = (
                    f"@{user.username}" if user.username else user.full_name
                )
            except TelegramAPIError:
                user_labels[user_id] = "профиль недоступен"
        return escape(user_labels[user_id])

    action_labels = {
        "warn": "WARN",
        "clear_warnings": "СНЯТИЕ WARN",
        "mute": "MUTE",
        "unmute": "UNMUTE",
        "kick": "KICK",
        "ban": "BAN",
        "unban": "UNBAN",
    }
    for row in rows:
        actor = await display_user(int(row["actor_id"]))
        target = await display_user(int(row["target_id"]))
        created = escape(row["created_at"][:16].replace("T", " "))
        action = escape(action_labels.get(row["action"], row["action"].upper()))
        details = f"\n   Причина/детали: {escape(row['details'])}" if row["details"] else ""
        lines.append(
            f"<code>{created}</code> · <b>{action}</b>\n"
            f"   Модератор: {actor}\n"
            f"   Участник: {target}{details}"
        )
    await message.answer("\n\n".join(lines))
