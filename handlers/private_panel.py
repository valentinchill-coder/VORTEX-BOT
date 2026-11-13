from datetime import datetime, timedelta, timezone
from html import escape

import aiosqlite
from aiogram import Bot, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, ChatPermissions
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.db import Database

router = Router()


async def _safe_edit(message: Message, text: str, reply_markup=None) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if "message is not modified" not in exc.message.lower():
            raise
pending_action: dict[int, tuple[int, str]] = {}


async def allowed(bot: Bot, user_id: int, chat_id: int, owner_ids: frozenset[int]) -> bool:
    if user_id in owner_ids:
        return True
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)
    except TelegramAPIError:
        return False


async def known_groups(db: Database) -> list[int]:
    async with aiosqlite.connect(db.path) as conn:
        cur = await conn.execute("SELECT DISTINCT chat_id FROM users ORDER BY chat_id DESC")
        return [int(row[0]) for row in await cur.fetchall()]


def groups_keyboard(groups: list[tuple[int, str]]):
    kb = InlineKeyboardBuilder()
    for chat_id, title in groups:
        kb.button(text=title[:50], callback_data=f"vp:group:{chat_id}")
    kb.adjust(1)
    return kb.as_markup()


def group_keyboard(chat_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Статистика", callback_data=f"vp:stats:{chat_id}")
    kb.button(text="🏆 Активные участники", callback_data=f"vp:top:{chat_id}")
    kb.button(text="🛡 Модерация", callback_data=f"vp:mod:{chat_id}")
    kb.button(text="🔄 Обновить", callback_data=f"vp:group:{chat_id}")
    kb.button(text="⬅️ К списку групп", callback_data="vp:groups")
    kb.adjust(1)
    return kb.as_markup()


def moderation_keyboard(chat_id: int):
    kb = InlineKeyboardBuilder()
    for label, action in [
        ("⚠️ Предупредить", "warn"),
        ("🔇 Мут на 10 минут", "mute"),
        ("🔊 Снять мут", "unmute"),
        ("👢 Исключить", "kick"),
        ("⛔ Заблокировать", "ban"),
        ("🧹 Очистить предупреждения", "clearwarns"),
    ]:
        kb.button(text=label, callback_data=f"vp:action:{action}:{chat_id}")
    kb.button(text="⬅️ Назад", callback_data=f"vp:group:{chat_id}")
    kb.adjust(1)
    return kb.as_markup()


def profile_groups_keyboard(groups):
    kb = InlineKeyboardBuilder()
    for chat_id, title in groups:
        kb.button(text=f"👤 {title[:45]}", callback_data=f"vp:myprofile:{chat_id}")
    kb.adjust(1)
    return kb.as_markup()


async def user_profile_groups(db: Database, user_id: int):
    async with aiosqlite.connect(db.path) as conn:
        cur = await conn.execute("SELECT DISTINCT chat_id FROM users WHERE user_id=? ORDER BY chat_id DESC", (user_id,))
        return [int(row[0]) for row in await cur.fetchall()]


@router.callback_query(lambda q: q.data == "vp:myprofile")
async def choose_profile_group(query: CallbackQuery, db: Database):
    if not query.message or not query.from_user or query.message.chat.type != "private":
        await query.answer()
        return
    groups = []
    for chat_id in await user_profile_groups(db, query.from_user.id):
        try:
            chat = await query.bot.get_chat(chat_id)
            groups.append((chat_id, chat.title or str(chat_id)))
        except TelegramAPIError:
            continue
    if groups:
        await query.message.answer("Выбери группу для просмотра своего профиля:", reply_markup=profile_groups_keyboard(groups))
    else:
        await query.message.answer("Пока нет данных профиля. Напиши несколько сообщений в группе, где работает VORTEX.")
    await query.answer()


@router.callback_query(lambda q: q.data and q.data.startswith("vp:myprofile:"))
async def show_private_profile(query: CallbackQuery, bot: Bot, db: Database):
    if not query.message or not query.from_user or query.message.chat.type != "private":
        await query.answer()
        return
    try:
        chat_id = int(query.data.rsplit(":", 1)[1])
    except ValueError:
        await query.answer("Некорректная группа.", show_alert=True)
        return
    async with aiosqlite.connect(db.path) as conn:
        cur = await conn.execute("SELECT 1 FROM users WHERE chat_id=? AND user_id=?", (chat_id, query.from_user.id))
        if not await cur.fetchone():
            await query.answer("Профиль не найден.", show_alert=True)
            return
        cur = await conn.execute("SELECT points,wins,played FROM game_stats WHERE chat_id=? AND user_id=?", (chat_id, query.from_user.id))
        game = await cur.fetchone() or (0, 0, 0)
        cur = await conn.execute("SELECT item_code,quantity FROM user_items WHERE chat_id=? AND user_id=? AND quantity>0 ORDER BY item_code", (chat_id, query.from_user.id))
        inventory = await cur.fetchall()
    try:
        member = await bot.get_chat_member(chat_id, query.from_user.id)
        if member.status in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
            await query.answer("Ты больше не состоишь в этой группе.", show_alert=True)
            return
        chat = await bot.get_chat(chat_id)
    except TelegramAPIError:
        await query.answer("Не удалось проверить участие в группе.", show_alert=True)
        return
    data = await db.get_profile(chat_id, query.from_user.id)
    user = data["user"] or {}
    balance = await db.get_balance(chat_id, query.from_user.id)
    messages = int(user.get("message_count", 0))
    rank = "🌪 Легенда" if messages >= 1000 else "💎 Ветеран" if messages >= 500 else "🔥 Активный" if messages >= 150 else "⭐ Участник" if messages >= 30 else "🌱 Новичок"
    from handlers.shop import ITEMS
    items = [f"{ITEMS.get(code, {}).get('name', code)} ×{qty}" for code, qty in inventory]
    username = f"@{escape(query.from_user.username)}" if query.from_user.username else "не указан"
    await query.message.answer(
        f"👤 <b>Твой профиль VORTEX</b>\nГруппа: <b>{escape(chat.title or str(chat_id))}</b>\n\n"
        f"Имя: <b>{escape(query.from_user.full_name)}</b>\nUsername: {username}\nРанг: {rank}\n"
        f"Сообщений: <b>{messages}</b>\nРепутация: <b>{data['reputation']}</b> ⭐\n"
        f"Предупреждений: <b>{data['warnings']}</b>\n\n"
        f"💰 Баланс: <b>{balance} V-coins</b>\n🎮 Игровые очки: <b>{game[0]}</b>\n"
        f"🏆 Побед: <b>{game[1]}</b> из {game[2]} игр\n"
        f"🎒 Инвентарь: " + (", ".join(items) if items else "пуст")
    )
    await query.answer()


@router.message(Command("start"), lambda m: m.chat.type == "private")
async def private_start(message: Message, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not message.from_user:
        return
    pending_action.pop(message.from_user.id, None)
    groups = []
    for chat_id in await known_groups(db):
        if not await allowed(bot, message.from_user.id, chat_id, owner_ids):
            continue
        try:
            chat = await bot.get_chat(chat_id)
            groups.append((chat_id, chat.title or str(chat_id)))
        except TelegramAPIError:
            continue
    kb = InlineKeyboardBuilder()
    kb.button(text="👤 Мой профиль", callback_data="vp:myprofile")
    if groups:
        kb.button(text="🛡 Управление группой", callback_data="vp:groups")
    kb.adjust(1)
    await message.answer(
        "🌪 <b>VORTEX — личный кабинет</b>\n\n"
        "Профиль доступен каждому участнику. Управление группой отображается только администраторам и владельцу.",
        reply_markup=kb.as_markup(),
    )


@router.message(Command("profile"), lambda m: m.chat.type == "private")
async def private_profile_command(message: Message, db: Database):
    if not message.from_user:
        return
    pending_action.pop(message.from_user.id, None)
    groups = []
    for chat_id in await user_profile_groups(db, message.from_user.id):
        try:
            chat = await message.bot.get_chat(chat_id)
            groups.append((chat_id, chat.title or str(chat_id)))
        except TelegramAPIError:
            continue
    if groups:
        await message.answer("Выбери группу для просмотра своего профиля:", reply_markup=profile_groups_keyboard(groups))
    else:
        await message.answer("Пока нет данных профиля. Напиши несколько сообщений в группе, где работает VORTEX.")


@router.message(Command("help"), lambda m: m.chat.type == "private")
async def private_help(message: Message):
    await message.answer(
        "📖 В личном чате доступны просмотр своего профиля и личный кабинет. "
        "Управление группой возможно только для её администраторов или владельца."
    )


@router.message(lambda m: m.chat.type == "private" and m.text and m.text.startswith("/") and m.text.split(maxsplit=1)[0].split("@", 1)[0] not in {"/start", "/profile", "/cancel"})
async def block_private_commands(message: Message):
    await message.answer("В личном чате доступны просмотр своего профиля и личный кабинет. Команды управления группой работают только при наличии прав администратора в самой группе.")


@router.callback_query(lambda q: q.data == "vp:groups")
async def show_groups(query: CallbackQuery, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not query.message or not query.from_user or query.message.chat.type != "private":
        await query.answer()
        return
    groups = []
    for chat_id in await known_groups(db):
        if not await allowed(bot, query.from_user.id, chat_id, owner_ids):
            continue
        try:
            chat = await bot.get_chat(chat_id)
            groups.append((chat_id, chat.title or str(chat_id)))
        except TelegramAPIError:
            pass
    if groups:
        await _safe_edit(query.message, "Выбери беседу для управления:", reply_markup=groups_keyboard(groups))
    else:
        await _safe_edit(query.message, "Нет доступных групп.")
    await query.answer()


@router.callback_query(lambda q: q.data and q.data.startswith("vp:group:"))
async def open_group(query: CallbackQuery, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not query.message or not query.from_user or query.message.chat.type != "private":
        await query.answer()
        return
    try:
        chat_id = int(query.data.rsplit(":", 1)[1])
    except ValueError:
        await query.answer("Некорректная группа.", show_alert=True)
        return
    if not await allowed(bot, query.from_user.id, chat_id, owner_ids):
        await query.answer("Доступ запрещён: нужны права администратора группы.", show_alert=True)
        return
    try:
        chat = await bot.get_chat(chat_id)
        title = escape(chat.title or str(chat_id))
    except TelegramAPIError:
        title = str(chat_id)
    data = await db.chat_stats(chat_id)
    await _safe_edit(query.message, 
        f"🌪 <b>{title}</b>\nID: <code>{chat_id}</code>\n\n"
        f"Участников с активностью: <b>{data['users']}</b>\n"
        f"Сообщений учтено: <b>{data['messages']}</b>\n"
        f"Предупреждений: <b>{data['warnings']}</b>\n"
        f"Срабатываний антифлуда: <b>{data['antiflood']}</b>\n\n"
        "Выбери раздел управления:",
        reply_markup=group_keyboard(chat_id),
    )
    await query.answer()


@router.callback_query(lambda q: q.data and q.data.startswith("vp:stats:"))
async def group_stats(query: CallbackQuery, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not query.message or not query.from_user or query.message.chat.type != "private":
        await query.answer()
        return
    try:
        chat_id = int(query.data.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        await query.answer("Некорректная группа.", show_alert=True)
        return
    if not await allowed(bot, query.from_user.id, chat_id, owner_ids):
        await query.answer("Доступ запрещён.", show_alert=True)
        return
    data = await db.chat_stats(chat_id)
    await _safe_edit(query.message, 
        "📊 <b>Статистика беседы</b>\n\n"
        f"Участников с активностью: <b>{data['users']}</b>\n"
        f"Сообщений: <b>{data['messages']}</b>\n"
        f"Предупреждений: <b>{data['warnings']}</b>\n"
        f"Антифлуд: <b>{data['antiflood']}</b>",
        reply_markup=group_keyboard(chat_id),
    )
    await query.answer()


@router.callback_query(lambda q: q.data and q.data.startswith("vp:top:"))
async def group_top(query: CallbackQuery, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not query.message or not query.from_user or query.message.chat.type != "private":
        await query.answer()
        return
    try:
        chat_id = int(query.data.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        await query.answer("Некорректная группа.", show_alert=True)
        return
    if not await allowed(bot, query.from_user.id, chat_id, owner_ids):
        await query.answer("Доступ запрещён.", show_alert=True)
        return
    rows = await db.top_activity(chat_id, 10)
    lines = []
    for index, (user_id, count) in enumerate(rows, 1):
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            name = escape(member.user.full_name)
        except TelegramAPIError:
            name = f"ID {user_id}"
        lines.append(f"{index}. {name} — {count} сообщ.")
    await _safe_edit(query.message, 
        "🏆 <b>Топ активности</b>\n\n" + ("\n".join(lines) if lines else "Пока нет данных."),
        reply_markup=group_keyboard(chat_id),
    )
    await query.answer()


@router.callback_query(lambda q: q.data and q.data.startswith("vp:mod:"))
async def moderation_menu(query: CallbackQuery, bot: Bot, owner_ids: frozenset[int]):
    if not query.message or not query.from_user or query.message.chat.type != "private":
        await query.answer()
        return
    try:
        chat_id = int(query.data.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        await query.answer("Некорректная группа.", show_alert=True)
        return
    if not await allowed(bot, query.from_user.id, chat_id, owner_ids):
        await query.answer("Доступ запрещён.", show_alert=True)
        return
    await _safe_edit(query.message, 
        "🛡 <b>Модерация из личного чата</b>\n\n"
        "Выбери действие, затем отправь Telegram ID участника одним сообщением. "
        "Для отмены отправь /cancel.",
        reply_markup=moderation_keyboard(chat_id),
    )
    await query.answer()


@router.callback_query(lambda q: q.data and q.data.startswith("vp:action:"))
async def choose_action(query: CallbackQuery, bot: Bot, owner_ids: frozenset[int]):
    if not query.message or not query.from_user or query.message.chat.type != "private":
        await query.answer()
        return
    parts = query.data.split(":")
    if len(parts) != 4:
        await query.answer("Некорректное действие.", show_alert=True)
        return
    _, _, action, chat_id_raw = parts
    allowed_actions = {"warn", "mute", "unmute", "kick", "ban", "clearwarns"}
    if action not in allowed_actions:
        await query.answer("Неизвестное действие.", show_alert=True)
        return
    try:
        chat_id = int(chat_id_raw)
    except ValueError:
        await query.answer("Некорректная группа.", show_alert=True)
        return
    if not await allowed(bot, query.from_user.id, chat_id, owner_ids):
        await query.answer("Доступ запрещён.", show_alert=True)
        return
    pending_action[query.from_user.id] = (chat_id, action)
    await query.message.answer(
        f"Отправь Telegram ID участника для действия «{action}».\n"
        "Отмена: /cancel"
    )
    await query.answer()


@router.message(Command("cancel"), lambda m: m.chat.type == "private")
async def cancel_action(message: Message):
    if message.from_user:
        pending_action.pop(message.from_user.id, None)
    await message.answer("Действие отменено.")


@router.message(lambda m: m.chat.type == "private" and m.from_user and m.from_user.id in pending_action and not (m.text or "").startswith("/"))
async def execute_action(message: Message, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not message.from_user:
        return
    pending = pending_action.get(message.from_user.id)
    if not pending:
        return
    chat_id, action = pending
    if not await allowed(bot, message.from_user.id, chat_id, owner_ids):
        pending_action.pop(message.from_user.id, None)
        await message.answer("Доступ отозван. Операция отменена.")
        return
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Нужен числовой Telegram ID. Для отмены /cancel.")
        return
    user_id = int(raw)
    if user_id <= 0:
        await message.answer("Укажи корректный положительный Telegram ID.")
        return
    if user_id == message.from_user.id:
        await message.answer("Нельзя применить действие к самому себе.")
        return
    try:
        target = await bot.get_chat_member(chat_id, user_id)
        if target.user.is_bot:
            await message.answer("Нельзя применять действия к ботам.")
            pending_action.pop(message.from_user.id, None)
            return
        if target.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR) and action not in ("warn", "clearwarns"):
            await message.answer("Нельзя ограничивать или исключать администратора группы.")
            pending_action.pop(message.from_user.id, None)
            return
        if action == "warn":
            count = await db.add_warning(chat_id, user_id, message.from_user.id, "Из личной панели")
            await db.log_event(chat_id, "warn")
            result = f"⚠️ Выдано предупреждение. Всего: {count}."
        elif action == "clearwarns":
            await db.clear_warnings(chat_id, user_id)
            result = "🧹 Предупреждения очищены."
        elif action == "mute":
            await bot.restrict_chat_member(chat_id, user_id, permissions=ChatPermissions(can_send_messages=False),
                until_date=datetime.now(timezone.utc) + timedelta(minutes=10))
            result = "🔇 Участник ограничен на 10 минут."
        elif action == "unmute":
            chat_info = await bot.get_chat(chat_id)
            await bot.restrict_chat_member(chat_id, user_id, permissions=chat_info.permissions or ChatPermissions(
                can_send_messages=True, can_send_audios=True, can_send_documents=True, can_send_photos=True,
                can_send_videos=True, can_send_video_notes=True, can_send_voice_notes=True, can_send_polls=True,
                can_send_other_messages=True, can_add_web_page_previews=True))
            result = "🔊 Ограничения сняты."
        elif action == "kick":
            await bot.ban_chat_member(chat_id, user_id)
            await bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
            result = "👢 Участник исключён."
        elif action == "ban":
            await bot.ban_chat_member(chat_id, user_id)
            result = "⛔ Участник заблокирован."
        else:
            result = "Неизвестное действие."
        pending_action.pop(message.from_user.id, None)
        await message.answer(result)
        try:
            await bot.send_message(chat_id, f"🛡 Администратор выполнил действие: {escape(action)}.")
        except TelegramAPIError:
            pass
    except TelegramAPIError as exc:
        await message.answer(f"Не удалось выполнить действие: {escape(exc.message)}")
