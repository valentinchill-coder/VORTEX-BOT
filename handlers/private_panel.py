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

async def _safe_query_answer(query: CallbackQuery, *args, **kwargs) -> None:
    """Ignore expired callback-query acknowledgements; surface other API errors."""
    try:
        await query.answer(*args, **kwargs)
    except TelegramBadRequest as exc:
        message = exc.message.lower()
        if "query is too old" not in message and "query id is invalid" not in message:
            raise

pending_action: dict[int, tuple[int, str]] = {}
pending_filter_input: dict[int, int] = {}
pending_rank_target: dict[int, int] = {}


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
    kb.button(text="⚙️ Настройки защиты", callback_data=f"vp:settings:{chat_id}")
    kb.button(text="📋 Журнал действий", callback_data=f"vp:audit:{chat_id}")
    kb.button(text="🚫 Фильтры сообщений", callback_data=f"vp:filters:{chat_id}")
    kb.button(text="👑 Ранги модераторов", callback_data=f"vp:ranks:{chat_id}")
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
        await _safe_query_answer(query,)
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
    await _safe_query_answer(query,)


@router.callback_query(lambda q: q.data and q.data.startswith("vp:myprofile:"))
async def show_private_profile(query: CallbackQuery, bot: Bot, db: Database):
    if not query.message or not query.from_user or query.message.chat.type != "private":
        await _safe_query_answer(query,)
        return
    try:
        chat_id = int(query.data.rsplit(":", 1)[1])
    except ValueError:
        await _safe_query_answer(query,"Некорректная группа.", show_alert=True)
        return
    async with aiosqlite.connect(db.path) as conn:
        cur = await conn.execute("SELECT 1 FROM users WHERE chat_id=? AND user_id=?", (chat_id, query.from_user.id))
        if not await cur.fetchone():
            await _safe_query_answer(query,"Профиль не найден.", show_alert=True)
            return
        cur = await conn.execute("SELECT points,wins,played FROM game_stats WHERE chat_id=? AND user_id=?", (chat_id, query.from_user.id))
        game = await cur.fetchone() or (0, 0, 0)
        cur = await conn.execute("SELECT item_code,quantity FROM user_items WHERE chat_id=? AND user_id=? AND quantity>0 ORDER BY item_code", (chat_id, query.from_user.id))
        inventory = await cur.fetchall()
    try:
        member = await bot.get_chat_member(chat_id, query.from_user.id)
        if member.status in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
            await _safe_query_answer(query,"Ты больше не состоишь в этой группе.", show_alert=True)
            return
        chat = await bot.get_chat(chat_id)
    except TelegramAPIError:
        await _safe_query_answer(query,"Не удалось проверить участие в группе.", show_alert=True)
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
    await _safe_query_answer(query,)


@router.message(Command("start"), lambda m: m.chat.type == "private")
async def private_start(message: Message, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not message.from_user:
        return
    pending_action.pop(message.from_user.id, None)
    pending_filter_input.pop(message.from_user.id, None)
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
        await _safe_query_answer(query,)
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
    await _safe_query_answer(query,)


@router.callback_query(lambda q: q.data and q.data.startswith("vp:group:"))
async def open_group(query: CallbackQuery, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not query.message or not query.from_user or query.message.chat.type != "private":
        await _safe_query_answer(query,)
        return
    try:
        chat_id = int(query.data.rsplit(":", 1)[1])
    except ValueError:
        await _safe_query_answer(query,"Некорректная группа.", show_alert=True)
        return
    if not await allowed(bot, query.from_user.id, chat_id, owner_ids):
        await _safe_query_answer(query,"Доступ запрещён: нужны права администратора группы.", show_alert=True)
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
    await _safe_query_answer(query,)


@router.callback_query(lambda q: q.data and q.data.startswith("vp:stats:"))
async def group_stats(query: CallbackQuery, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not query.message or not query.from_user or query.message.chat.type != "private":
        await _safe_query_answer(query,)
        return
    try:
        chat_id = int(query.data.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        await _safe_query_answer(query,"Некорректная группа.", show_alert=True)
        return
    if not await allowed(bot, query.from_user.id, chat_id, owner_ids):
        await _safe_query_answer(query,"Доступ запрещён.", show_alert=True)
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
    await _safe_query_answer(query,)


@router.callback_query(lambda q: q.data and q.data.startswith("vp:top:"))
async def group_top(query: CallbackQuery, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not query.message or not query.from_user or query.message.chat.type != "private":
        await _safe_query_answer(query,)
        return
    try:
        chat_id = int(query.data.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        await _safe_query_answer(query,"Некорректная группа.", show_alert=True)
        return
    if not await allowed(bot, query.from_user.id, chat_id, owner_ids):
        await _safe_query_answer(query,"Доступ запрещён.", show_alert=True)
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
    await _safe_query_answer(query,)


@router.callback_query(lambda q: q.data and q.data.startswith("vp:mod:"))
async def moderation_menu(query: CallbackQuery, bot: Bot, owner_ids: frozenset[int]):
    if not query.message or not query.from_user or query.message.chat.type != "private":
        await _safe_query_answer(query,)
        return
    try:
        chat_id = int(query.data.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        await _safe_query_answer(query,"Некорректная группа.", show_alert=True)
        return
    if not await allowed(bot, query.from_user.id, chat_id, owner_ids):
        await _safe_query_answer(query,"Доступ запрещён.", show_alert=True)
        return
    await _safe_edit(query.message, 
        "🛡 <b>Модерация из личного чата</b>\n\n"
        "Выбери действие, затем отправь Telegram ID участника одним сообщением. "
        "Для отмены отправь /cancel.",
        reply_markup=moderation_keyboard(chat_id),
    )
    await _safe_query_answer(query,)


@router.callback_query(lambda q: q.data and q.data.startswith("vp:action:"))
async def choose_action(query: CallbackQuery, bot: Bot, owner_ids: frozenset[int]):
    if not query.message or not query.from_user or query.message.chat.type != "private":
        await _safe_query_answer(query,)
        return
    parts = query.data.split(":")
    if len(parts) != 4:
        await _safe_query_answer(query,"Некорректное действие.", show_alert=True)
        return
    _, _, action, chat_id_raw = parts
    allowed_actions = {"warn", "mute", "unmute", "kick", "ban", "clearwarns"}
    if action not in allowed_actions:
        await _safe_query_answer(query,"Неизвестное действие.", show_alert=True)
        return
    try:
        chat_id = int(chat_id_raw)
    except ValueError:
        await _safe_query_answer(query,"Некорректная группа.", show_alert=True)
        return
    if not await allowed(bot, query.from_user.id, chat_id, owner_ids):
        await _safe_query_answer(query,"Доступ запрещён.", show_alert=True)
        return
    pending_action[query.from_user.id] = (chat_id, action)
    await query.message.answer(
        f"Отправь Telegram ID участника для действия «{action}».\n"
        "Отмена: /cancel"
    )
    await _safe_query_answer(query,)


@router.message(Command("cancel"), lambda m: m.chat.type == "private")
async def cancel_action(message: Message):
    if message.from_user:
        pending_action.pop(message.from_user.id, None)
        pending_filter_input.pop(message.from_user.id, None)
        pending_rank_target.pop(message.from_user.id, None)
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
            await bot.restrict_chat_member(chat_id, user_id, permissions=ChatPermissions(
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
                until_date=datetime.now(timezone.utc) + timedelta(minutes=10))
            result = "🔇 Участник ограничен на 10 минут."
        elif action == "unmute":
            chat_info = await bot.get_chat(chat_id)
            await bot.restrict_chat_member(chat_id, user_id, permissions=chat_info.permissions or ChatPermissions(
                can_send_messages=True, can_send_audios=True, can_send_documents=True, can_send_photos=True,
                can_send_videos=True, can_send_video_notes=True, can_send_voice_notes=True, can_send_polls=True,
                can_send_other_messages=True, can_add_web_page_previews=True, can_manage_topics=False))
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


async def _render_group_settings(query: CallbackQuery, chat_id: int, db: Database, bot: Bot, owner_ids: frozenset[int]):
    if not query.message or not query.from_user or query.message.chat.type != "private":
        await _safe_query_answer(query)
        return
    if not await allowed(bot, query.from_user.id, chat_id, owner_ids):
        await _safe_query_answer(query, "Доступ запрещён.", show_alert=True)
        return
    settings = await db.get_chat_settings(chat_id)
    enabled = settings["antiflood_enabled"] == "1"
    limit = int(settings["antiflood_limit"])
    window = int(settings["antiflood_window"])
    kb = InlineKeyboardBuilder()
    kb.button(text=f"Антифлуд: {'ВКЛ' if enabled else 'ВЫКЛ'}", callback_data=f"vp:setting:{chat_id}:antiflood_enabled")
    kb.button(text=f"Лимит: {limit} сообщ.", callback_data=f"vp:setting:{chat_id}:antiflood_limit")
    kb.button(text=f"Окно: {window} сек.", callback_data=f"vp:setting:{chat_id}:antiflood_window")
    kb.button(text="⬅️ Назад", callback_data=f"vp:group:{chat_id}")
    kb.adjust(1)
    await _safe_edit(query.message,
        "⚙️ <b>Настройки защиты группы</b>\n\n"
        f"Антифлуд: <b>{'включён' if enabled else 'выключен'}</b>\n"
        f"Лимит: <b>{limit} сообщений</b> за <b>{window} секунд</b>\n\n"
        "Нажимай на параметры для переключения. Настройки сохраняются отдельно для каждой группы.",
        reply_markup=kb.as_markup(),
    )

@router.callback_query(lambda q: q.data and q.data.startswith("vp:settings:"))
async def show_group_settings(query: CallbackQuery, bot: Bot, db: Database, owner_ids: frozenset[int]):
    try:
        chat_id = int(query.data.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        await _safe_query_answer(query, "Некорректная группа.", show_alert=True)
        return
    await _render_group_settings(query, chat_id, db, bot, owner_ids)
    await _safe_query_answer(query)

@router.callback_query(lambda q: q.data and q.data.startswith("vp:setting:"))
async def update_group_setting(query: CallbackQuery, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not query.from_user or not query.message or query.message.chat.type != "private":
        await _safe_query_answer(query)
        return
    parts = query.data.split(":")
    if len(parts) != 4:
        await _safe_query_answer(query, "Некорректная настройка.", show_alert=True)
        return
    try:
        chat_id = int(parts[2])
    except ValueError:
        await _safe_query_answer(query, "Некорректная группа.", show_alert=True)
        return
    key = parts[3]
    if not await allowed(bot, query.from_user.id, chat_id, owner_ids):
        await _safe_query_answer(query, "Доступ запрещён.", show_alert=True)
        return
    settings = await db.get_chat_settings(chat_id)
    cycles = {"antiflood_enabled": ["1", "0"], "antiflood_limit": ["4", "6", "8", "10"], "antiflood_window": ["5", "8", "10", "15"]}
    if key not in cycles:
        await _safe_query_answer(query, "Неизвестная настройка.", show_alert=True)
        return
    values = cycles[key]
    current = settings[key]
    next_value = values[(values.index(current) + 1) % len(values)] if current in values else values[0]
    await db.set_chat_setting(chat_id, key, next_value, query.from_user.id)
    await _render_group_settings(query, chat_id, db, bot, owner_ids)
    await _safe_query_answer(query, "Настройка сохранена.")

@router.callback_query(lambda q: q.data and q.data.startswith("vp:audit:"))
async def group_audit_log(query: CallbackQuery, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not query.message or not query.from_user or query.message.chat.type != "private":
        await _safe_query_answer(query)
        return
    try:
        chat_id = int(query.data.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        await _safe_query_answer(query, "Некорректная группа.", show_alert=True)
        return
    if not await allowed(bot, query.from_user.id, chat_id, owner_ids):
        await _safe_query_answer(query, "Доступ запрещён.", show_alert=True)
        return
    rows = await db.recent_moderation_actions(chat_id, 10)
    lines = ["📋 <b>Последние действия администраторов</b>", ""]
    for row in rows:
        action = escape(str(row.get("action", "action")))
        details = escape(str(row.get("details", "")))
        stamp = escape(str(row.get("created_at", ""))[:16].replace("T", " "))
        target = f" → <code>{int(row.get('target_id', 0))}</code>" if int(row.get("target_id", 0)) else ""
        lines.append(f"• <b>{action}</b>{target}\n  <code>{stamp}</code> {details}")
    if not rows:
        lines.append("Журнал пока пуст.")
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Обновить", callback_data=f"vp:audit:{chat_id}")
    kb.button(text="⬅️ Назад", callback_data=f"vp:group:{chat_id}")
    kb.adjust(1)
    await _safe_edit(query.message, "\n".join(lines), reply_markup=kb.as_markup())
    await _safe_query_answer(query)


async def _render_filters(query: CallbackQuery, chat_id: int, db: Database, bot: Bot, owner_ids: frozenset[int]):
    if not query.message or not query.from_user or query.message.chat.type != "private":
        await _safe_query_answer(query)
        return
    if not await allowed(bot, query.from_user.id, chat_id, owner_ids):
        await _safe_query_answer(query, "Доступ запрещён.", show_alert=True)
        return
    settings = await db.get_chat_settings(chat_id)
    words = await db.list_blocked_words(chat_id)
    kb = InlineKeyboardBuilder()
    kb.button(text=f"Фильтр ссылок: {'ВКЛ' if settings['link_filter_enabled']=='1' else 'ВЫКЛ'}", callback_data=f"vp:filtertoggle:{chat_id}:link_filter_enabled")
    kb.button(text=f"Запрещённые слова: {'ВКЛ' if settings['word_filter_enabled']=='1' else 'ВЫКЛ'}", callback_data=f"vp:filtertoggle:{chat_id}:word_filter_enabled")
    kb.button(text="➕ Добавить слово/фразу", callback_data=f"vp:filteradd:{chat_id}")
    for word in words[:12]:
        kb.button(text=f"❌ {word[:28]}", callback_data=f"vp:filterremove:{chat_id}:{words.index(word)}")
    kb.button(text="⬅️ Назад", callback_data=f"vp:group:{chat_id}")
    kb.adjust(1)
    word_text = "\n".join(f"• {escape(w)}" for w in words) if words else "Список пуст."
    await _safe_edit(query.message,
        "🚫 <b>Фильтры сообщений</b>\n\n"
        f"Ссылки: <b>{'включены' if settings['link_filter_enabled']=='1' else 'выключены'}</b>\n"
        f"Запрещённые слова: <b>{'включены' if settings['word_filter_enabled']=='1' else 'выключены'}</b>\n\n"
        f"<b>Список слов и фраз:</b>\n{word_text}\n\n"
        "Добавляй короткие слова или фразы (до 32 символов). Удаление фильтрует только новые сообщения.",
        reply_markup=kb.as_markup(),
    )

@router.callback_query(lambda q: q.data and q.data.startswith("vp:filters:"))
async def show_filters(query: CallbackQuery, bot: Bot, db: Database, owner_ids: frozenset[int]):
    try:
        chat_id = int(query.data.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        await _safe_query_answer(query, "Некорректная группа.", show_alert=True)
        return
    await _render_filters(query, chat_id, db, bot, owner_ids)
    await _safe_query_answer(query)

@router.callback_query(lambda q: q.data and q.data.startswith("vp:filtertoggle:"))
async def toggle_filter(query: CallbackQuery, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not query.from_user or not query.message or query.message.chat.type != "private":
        await _safe_query_answer(query)
        return
    parts = query.data.split(":")
    if len(parts) != 4:
        await _safe_query_answer(query, "Некорректная настройка.", show_alert=True)
        return
    try:
        chat_id = int(parts[2])
    except ValueError:
        await _safe_query_answer(query, "Некорректная группа.", show_alert=True)
        return
    key = parts[3]
    if key not in {"link_filter_enabled", "word_filter_enabled"} or not await allowed(bot, query.from_user.id, chat_id, owner_ids):
        await _safe_query_answer(query, "Нет доступа или неверная настройка.", show_alert=True)
        return
    current = (await db.get_chat_settings(chat_id))[key]
    await db.set_chat_setting(chat_id, key, "0" if current == "1" else "1", query.from_user.id)
    await _render_filters(query, chat_id, db, bot, owner_ids)
    await _safe_query_answer(query, "Настройка сохранена.")

@router.callback_query(lambda q: q.data and q.data.startswith("vp:filteradd:"))
async def start_add_filter_word(query: CallbackQuery, bot: Bot, owner_ids: frozenset[int]):
    if not query.from_user or not query.message or query.message.chat.type != "private":
        await _safe_query_answer(query)
        return
    try:
        chat_id = int(query.data.rsplit(":", 1)[1])
    except ValueError:
        await _safe_query_answer(query, "Некорректная группа.", show_alert=True)
        return
    if not await allowed(bot, query.from_user.id, chat_id, owner_ids):
        await _safe_query_answer(query, "Доступ запрещён.", show_alert=True)
        return
    pending_filter_input[query.from_user.id] = chat_id
    await query.message.answer("Отправь слово или короткую фразу (до 32 символов, максимум 3 слова). Для отмены — /cancel.")
    await _safe_query_answer(query)

@router.callback_query(lambda q: q.data and q.data.startswith("vp:filterremove:"))
async def remove_filter_word(query: CallbackQuery, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not query.from_user or not query.message or query.message.chat.type != "private":
        await _safe_query_answer(query)
        return
    parts = query.data.split(":", 3)
    if len(parts) != 4:
        await _safe_query_answer(query, "Некорректное слово.", show_alert=True)
        return
    try:
        chat_id = int(parts[2])
    except ValueError:
        await _safe_query_answer(query, "Некорректная группа.", show_alert=True)
        return
    if not await allowed(bot, query.from_user.id, chat_id, owner_ids):
        await _safe_query_answer(query, "Доступ запрещён.", show_alert=True)
        return
    words = await db.list_blocked_words(chat_id)
    try:
        index = int(parts[3])
        word = words[index]
    except (ValueError, IndexError):
        await _safe_query_answer(query, "Слово уже удалено или список изменился.", show_alert=True)
        return
    await db.remove_blocked_word(chat_id, word, query.from_user.id)
    await _render_filters(query, chat_id, db, bot, owner_ids)
    await _safe_query_answer(query, "Слово удалено из списка.")

@router.message(lambda m: m.chat.type == "private" and m.from_user and m.from_user.id in pending_filter_input and not (m.text or "").startswith("/"))
async def save_filter_word(message: Message, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not message.from_user:
        return
    chat_id = pending_filter_input.get(message.from_user.id)
    if chat_id is None:
        return
    if not await allowed(bot, message.from_user.id, chat_id, owner_ids):
        pending_filter_input.pop(message.from_user.id, None)
        await message.answer("Доступ отозван. Добавление отменено.")
        return
    word = (message.text or "").strip()
    try:
        if not word:
            raise ValueError()
        added = await db.add_blocked_word(chat_id, word, message.from_user.id)
    except ValueError:
        await message.answer("Не подходит: используй 1–32 символа и не более 3 слов.")
        return
    pending_filter_input.pop(message.from_user.id, None)
    await message.answer("Фраза добавлена в список." if added else "Такая фраза уже есть.")



async def _rank_actor_level(bot: Bot, user_id: int, chat_id: int, owner_ids: frozenset[int], db: Database) -> int:
    if user_id in owner_ids:
        return 7
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        if member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR):
            return 6
    except TelegramAPIError:
        return 0
    return await db.get_moderation_rank(chat_id, user_id)


async def _render_rank_panel(query: CallbackQuery, chat_id: int, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not query.message or not query.from_user or query.message.chat.type != "private":
        return
    actor_rank = await _rank_actor_level(bot, query.from_user.id, chat_id, owner_ids, db)
    if actor_rank < 5:
        return
    async with aiosqlite.connect(db.path) as conn:
        cur = await conn.execute("SELECT user_id, rank FROM moderation_ranks WHERE chat_id=? ORDER BY rank DESC, updated_at DESC LIMIT 30", (chat_id,))
        assigned = await cur.fetchall()
    lines = ["👑 <b>Ранги модераторов</b>", "", "Назначенные ранги:"]
    if assigned:
        for uid, rank in assigned:
            try:
                member = await bot.get_chat_member(chat_id, int(uid))
                display = escape(member.user.full_name)
            except TelegramAPIError:
                display = f"ID {uid}"
            lines.append(f"• {display} — ранг <b>{rank}</b>")
    else:
        lines.append("Пока никому не назначены.")
    lines.extend(["", "Главный модератор назначает ранги 1–3.", "Администратор группы и владелец могут назначать ранги 1–5."])
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Назначить / изменить ранг", callback_data=f"vp:rankadd:{chat_id}")
    kb.button(text="⬅️ Назад", callback_data=f"vp:group:{chat_id}")
    kb.adjust(1)
    await _safe_edit(query.message, "\n".join(lines), reply_markup=kb.as_markup())


@router.callback_query(lambda q: q.data and q.data.startswith("vp:ranks:"))
async def show_rank_panel(query: CallbackQuery, bot: Bot, db: Database, owner_ids: frozenset[int]):
    try:
        chat_id = int(query.data.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        await _safe_query_answer(query, "Некорректная группа.", show_alert=True)
        return
    if await _rank_actor_level(bot, query.from_user.id, chat_id, owner_ids, db) < 5:
        await _safe_query_answer(query, "Управлять рангами может главный модератор или администратор группы.", show_alert=True)
        return
    await _render_rank_panel(query, chat_id, bot, db, owner_ids)
    await _safe_query_answer(query)


@router.callback_query(lambda q: q.data and q.data.startswith("vp:rankadd:"))
async def begin_rank_assignment(query: CallbackQuery, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not query.from_user or not query.message or query.message.chat.type != "private":
        await _safe_query_answer(query)
        return
    try:
        chat_id = int(query.data.rsplit(":", 1)[1])
    except ValueError:
        await _safe_query_answer(query, "Некорректная группа.", show_alert=True)
        return
    actor_rank = await _rank_actor_level(bot, query.from_user.id, chat_id, owner_ids, db)
    if actor_rank < 5:
        await _safe_query_answer(query, "Недостаточно прав.", show_alert=True)
        return
    pending_rank_target[query.from_user.id] = chat_id
    await query.message.answer("Отправь Telegram ID участника группы, которому нужно назначить или изменить ранг. Отмена: /cancel")
    await _safe_query_answer(query)


@router.message(lambda m: m.chat.type == "private" and m.from_user and m.from_user.id in pending_rank_target and not (m.text or "").startswith("/"))
async def receive_rank_target(message: Message, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not message.from_user:
        return
    chat_id = pending_rank_target.get(message.from_user.id)
    if chat_id is None:
        return
    actor_rank = await _rank_actor_level(bot, message.from_user.id, chat_id, owner_ids, db)
    if actor_rank < 5:
        pending_rank_target.pop(message.from_user.id, None)
        await message.answer("Доступ отозван. Операция отменена.")
        return
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Нужен числовой Telegram ID. Попробуй ещё раз или /cancel.")
        return
    target_id = int(raw)
    if target_id <= 0:
        await message.answer("Некорректный ID.")
        return
    try:
        member = await bot.get_chat_member(chat_id, target_id)
    except TelegramAPIError:
        await message.answer("Не удалось найти участника в этой группе. Проверь ID.")
        return
    if member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR) or target_id in owner_ids or member.user.is_bot:
        await message.answer("Нельзя назначать внутренний ранг администратору Telegram, владельцу или боту.")
        return
    current = await db.get_moderation_rank(chat_id, target_id)
    if current >= actor_rank:
        await message.answer("Нельзя менять ранг равного или старшего по иерархии.")
        return
    pending_rank_target.pop(message.from_user.id, None)
    kb = InlineKeyboardBuilder()
    max_rank = 3 if actor_rank == 5 else 5
    for rank in range(1, max_rank + 1):
        kb.button(text=f"{rank} — {['','Стажёр','Младший модератор','Модератор','Старший модератор','Главный модератор'][rank]}", callback_data=f"vp:rankset:{chat_id}:{target_id}:{rank}")
    if current:
        kb.button(text="Снять ранг", callback_data=f"vp:rankset:{chat_id}:{target_id}:0")
    kb.button(text="Отмена", callback_data=f"vp:ranks:{chat_id}")
    kb.adjust(1)
    await message.answer(f"Участник: <b>{escape(member.user.full_name)}</b>\nТекущий ранг: {current}\nВыбери новый ранг:", reply_markup=kb.as_markup())


@router.callback_query(lambda q: q.data and q.data.startswith("vp:rankset:"))
async def apply_rank_assignment(query: CallbackQuery, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not query.from_user or not query.message or query.message.chat.type != "private":
        await _safe_query_answer(query)
        return
    parts = query.data.split(":")
    if len(parts) != 5:
        await _safe_query_answer(query, "Некорректное действие.", show_alert=True)
        return
    try:
        chat_id, target_id, new_rank = map(int, parts[2:])
    except ValueError:
        await _safe_query_answer(query, "Некорректные данные.", show_alert=True)
        return
    actor_rank = await _rank_actor_level(bot, query.from_user.id, chat_id, owner_ids, db)
    if actor_rank < 5 or not 0 <= new_rank <= (3 if actor_rank == 5 else 5):
        await _safe_query_answer(query, "Недостаточно прав или неверный ранг.", show_alert=True)
        return
    try:
        member = await bot.get_chat_member(chat_id, target_id)
    except TelegramAPIError:
        await _safe_query_answer(query, "Участник больше не состоит в группе.", show_alert=True)
        return
    if member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR) or target_id in owner_ids or member.user.is_bot:
        await _safe_query_answer(query, "Нельзя менять ранг этому участнику.", show_alert=True)
        return
    current = await db.get_moderation_rank(chat_id, target_id)
    if current >= actor_rank or new_rank >= actor_rank:
        await _safe_query_answer(query, "Нельзя менять равный или старший ранг.", show_alert=True)
        return
    if current == new_rank:
        await _safe_query_answer(query, "Этот ранг уже установлен.", show_alert=True)
        return
    await db.set_moderation_rank(chat_id, target_id, new_rank, query.from_user.id)
    await db.log_moderation_action(chat_id, query.from_user.id, target_id, "rank_change", f"{current} -> {new_rank}")
    await _render_rank_panel(query, chat_id, bot, db, owner_ids)
    await _safe_query_answer(query, "Ранг обновлён.")
