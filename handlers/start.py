from datetime import datetime, timedelta, timezone
from html import escape

from aiogram import Bot, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, ChatPermissions
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.db import Database

router = Router()

# Pending participant selection: (chat_id, admin_id)
pending_selection: set[tuple[int, int]] = set()


def main_menu():
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🛡 Модерация", callback_data="vortex:moderation")
    keyboard.button(text="👤 Выбрать участника", callback_data="vortex:select_member")
    keyboard.button(text="⚠️ Предупреждения", callback_data="vortex:warnings")
    keyboard.button(text="🚫 Антифлуд", callback_data="vortex:antiflood")
    keyboard.button(text="📊 Статистика", callback_data="vortex:stats")
    keyboard.button(text="👤 Профиль", callback_data="vortex:profile")
    keyboard.button(text="⭐ Репутация", callback_data="vortex:reputation")
    keyboard.button(text="💰 Экономика", callback_data="vortex:economy")
    keyboard.button(text="👋 Приветствие", callback_data="vortex:welcome")
    keyboard.button(text="📖 Все команды", callback_data="vortex:commands")
    keyboard.adjust(2, 2, 2, 2, 2)
    return keyboard.as_markup()


def back_menu():
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="⬅️ В главное меню", callback_data="vortex:home")
    return keyboard.as_markup()


def member_actions(chat_id: int, user_id: int):
    keyboard = InlineKeyboardBuilder()
    for label, action in [
        ("⚠️ Выдать предупреждение", "warn"),
        ("🔇 Мут на 10 минут", "mute"),
        ("🔊 Снять мут", "unmute"),
        ("👢 Исключить", "kick"),
        ("⛔ Заблокировать", "ban"),
        ("🧹 Очистить предупреждения", "clearwarns"),
    ]:
        keyboard.button(text=label, callback_data=f"vortex:act:{action}:{chat_id}:{user_id}")
    keyboard.button(text="⬅️ В главное меню", callback_data="vortex:home")
    keyboard.adjust(1)
    return keyboard.as_markup()


MENU_TEXT = {
    "moderation": (
        "🛡 <b>Модерация</b>\n\n"
        "Нажми «Выбрать участника», чтобы открыть действия для конкретного пользователя. "
        "Также можно использовать команды ответом на его сообщение:\n"
        "/mute 10m — ограничить на 10 минут\n"
        "/unmute — снять ограничение\n"
        "/kick — удалить из группы\n"
        "/ban — заблокировать\n"
        "/unban ID — снять блокировку по Telegram ID"
    ),
    "warnings": (
        "⚠️ <b>Предупреждения</b>\n\n"
        "Нажми «Выбрать участника» в главном меню, чтобы выдать или очистить предупреждения.\n"
        "/warn, /warnings, /clearwarns — также работают ответом на сообщение участника."
    ),
    "antiflood": (
        "🚫 <b>Защита от флуда</b>\n\n"
        "Антифлуд включён автоматически: бот отслеживает частые сообщения "
        "и удаляет сообщения сверх установленного лимита (6 сообщений за 8 секунд)."
    ),
    "stats": (
        "📊 <b>Статистика</b>\n\n"
        "Отправь команду /stats в группе, чтобы посмотреть количество "
        "предупреждений, выданных ботом."
    ),
    "profile": (
        "👤 <b>Профили участников</b>\n\n"
        "/profile — посмотреть свой профиль\n"
        "Ответь командой /profile на сообщение, чтобы посмотреть профиль другого участника."
    ),
    "reputation": (
        "⭐ <b>Репутация</b>\n\n"
        "Ответь командой /rep на сообщение, чтобы выдать +1 репутации.\n"
        "/toprep — рейтинг участников. Повторно выдать репутацию одному человеку можно на следующий день."
    ),
    "economy": (
        "💰 <b>Экономика VORTEX</b>\n\n"
        "/balance — посмотреть баланс\n"
        "/daily — получить ежедневные 100 V-coins\n"
        "Ответь командой /pay 50 на сообщение участника, чтобы перевести ему 50 монет.\n"
        "/topmoney — рейтинг богачей группы"
    ),
    "welcome": (
        "👋 <b>Приветствие</b>\n\n"
        "Бот автоматически приветствует новых участников, когда они вступают в группу."
    ),
    "commands": (
        "📖 <b>Список команд</b>\n\n"
        "/help — открыть справку\n"
        "/warn — предупреждение (ответом)\n"
        "/warnings — число предупреждений (ответом)\n"
        "/clearwarns — очистить предупреждения (ответом)\n"
        "/mute 10m — ограничить пользователя (ответом)\n"
        "/unmute — снять ограничение (ответом)\n"
        "/kick — удалить из группы (ответом)\n"
        "/ban — заблокировать (ответом)\n"
        "/unban ID — разблокировать по Telegram ID\n"
        "/profile — профиль участника\n"
        "/rep — выдать репутацию (ответом)\n"
        "/toprep — топ репутации\n"
        "/stats — статистика группы"
    ),
}


async def user_is_admin(bot: Bot, chat_id: int, user_id: int, owner_ids: frozenset[int]) -> bool:
    if user_id in owner_ids:
        return True
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)
    except TelegramBadRequest:
        return False


@router.message(Command("start"))
async def start_command(message: Message):
    await message.answer(
        "🌪 <b>VORTEX BOT</b>\n"
        "Твой помощник по управлению Telegram-группой.\n\n"
        "Выбери нужный раздел в меню:",
        reply_markup=main_menu(),
    )


@router.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        "📖 <b>Справка VORTEX BOT</b>\n\n"
        "Выбери раздел в меню ниже. Команды модерации доступны администраторам группы.",
        reply_markup=main_menu(),
    )


@router.message(lambda message: message.chat.type != "private" and message.reply_to_message is not None and message.from_user is not None and (message.chat.id, message.from_user.id) in pending_selection)
async def receive_selected_member(message: Message, bot: Bot, owner_ids: frozenset[int]):
    if not message.from_user:
        return
    key = (message.chat.id, message.from_user.id)
    if key not in pending_selection:
        return
    pending_selection.discard(key)

    if not await user_is_admin(bot, message.chat.id, message.from_user.id, owner_ids):
        await message.answer("Выбирать участников через это меню могут только администраторы.")
        return
    target = message.reply_to_message.from_user
    if not target:
        await message.answer("Не удалось определить автора сообщения. Ответь на обычное сообщение участника.")
        return
    if target.is_bot:
        await message.answer("Нельзя применить действия к боту.")
        return
    if target.id == message.from_user.id:
        await message.answer("Нельзя выбрать самого себя.")
        return

    await message.answer(
        f"👤 Выбран участник: <b>{escape(target.full_name)}</b>\n"
        f"ID: <code>{target.id}</code>\n\n"
        "Выбери действие:",
        reply_markup=member_actions(message.chat.id, target.id),
    )


@router.callback_query(lambda query: query.data == "vortex:select_member")
async def select_member_callback(query: CallbackQuery, bot: Bot, owner_ids: frozenset[int]):
    if not query.message or not query.from_user:
        await query.answer()
        return
    if query.message.chat.type == "private":
        await query.answer("Открой меню в группе.", show_alert=True)
        return
    if not await user_is_admin(bot, query.message.chat.id, query.from_user.id, owner_ids):
        await query.answer("Только для администраторов группы.", show_alert=True)
        return
    pending_selection.add((query.message.chat.id, query.from_user.id))
    await query.message.answer(
        "👤 <b>Выбор участника</b>\n\n"
        "Найди сообщение нужного участника в чате и ответь на него любым текстом. "
        "После этого появится меню действий."
    )
    await query.answer()


@router.callback_query(lambda query: query.data and query.data.startswith("vortex:act:"))
async def member_action_callback(
    query: CallbackQuery,
    bot: Bot,
    db: Database,
    owner_ids: frozenset[int],
):
    if not query.message or not query.from_user:
        await query.answer()
        return
    parts = query.data.split(":")
    if len(parts) != 5:
        await query.answer("Некорректное действие.", show_alert=True)
        return
    _, _, action, chat_id_raw, user_id_raw = parts
    try:
        chat_id, user_id = int(chat_id_raw), int(user_id_raw)
    except ValueError:
        await query.answer("Некорректный участник.", show_alert=True)
        return
    if query.message.chat.id != chat_id:
        await query.answer("Это меню относится к другой группе.", show_alert=True)
        return
    if not await user_is_admin(bot, chat_id, query.from_user.id, owner_ids):
        await query.answer("Только для администраторов группы.", show_alert=True)
        return
    if user_id == query.from_user.id:
        await query.answer("Нельзя применить действие к самому себе.", show_alert=True)
        return
    try:
        target_member = await bot.get_chat_member(chat_id, user_id)
        target = target_member.user
        if (
            target_member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)
            and action not in ("warn", "clearwarns")
        ):
            await query.answer(
                "Администратора можно предупредить, но ограничить или исключить его через бота нельзя.",
                show_alert=True,
            )
            return

        if action == "warn":
            count = await db.add_warning(chat_id, user_id, query.from_user.id, "Выдано через меню")
            await db.log_event(chat_id, "warn")
            result = f"⚠️ {escape(target.full_name)} получил предупреждение. Всего: {count}."
        elif action == "clearwarns":
            await db.clear_warnings(chat_id, user_id)
            result = f"🧹 Предупреждения пользователя {escape(target.full_name)} очищены."
        elif action == "mute":
            await bot.restrict_chat_member(
                chat_id, user_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=datetime.now(timezone.utc) + timedelta(minutes=10),
            )
            result = f"🔇 {escape(target.full_name)} ограничен на 10 минут."
        elif action == "unmute":
            await bot.restrict_chat_member(
                chat_id, user_id,
                permissions=ChatPermissions(
                    can_send_messages=True, can_send_audios=True, can_send_documents=True,
                    can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
                    can_send_voice_notes=True, can_send_polls=True,
                    can_send_other_messages=True, can_add_web_page_previews=True,
                ),
            )
            result = f"🔊 Ограничения сняты: {escape(target.full_name)}."
        elif action == "kick":
            await bot.ban_chat_member(chat_id, user_id)
            await bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
            result = f"👢 {escape(target.full_name)} исключён из группы."
        elif action == "ban":
            await bot.ban_chat_member(chat_id, user_id)
            result = f"⛔ {escape(target.full_name)} заблокирован."
        else:
            await query.answer("Неизвестное действие.", show_alert=True)
            return
        await query.message.answer(result)
        await query.answer("Готово.")
    except TelegramBadRequest as exc:
        await query.answer(f"Не удалось выполнить действие: {exc.message}", show_alert=True)


@router.callback_query(lambda query: query.data and query.data.startswith("vortex:"))
async def menu_callback(query: CallbackQuery):
    section = query.data.split(":", 1)[1]
    if not query.message:
        await query.answer()
        return
    if section == "home":
        text = (
            "🌪 <b>VORTEX BOT</b>\n"
            "Твой помощник по управлению Telegram-группой.\n\n"
            "Выбери нужный раздел в меню:"
        )
        await query.message.edit_text(text, reply_markup=main_menu())
    elif section in MENU_TEXT:
        await query.message.edit_text(MENU_TEXT[section], reply_markup=back_menu())
    await query.answer()
