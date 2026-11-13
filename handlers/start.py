from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

router = Router()


def main_menu():
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🛡 Модерация", callback_data="vortex:moderation")
    keyboard.button(text="⚠️ Предупреждения", callback_data="vortex:warnings")
    keyboard.button(text="🚫 Антифлуд", callback_data="vortex:antiflood")
    keyboard.button(text="📊 Статистика", callback_data="vortex:stats")
    keyboard.button(text="👋 Приветствие", callback_data="vortex:welcome")
    keyboard.button(text="📖 Все команды", callback_data="vortex:commands")
    keyboard.adjust(2, 2, 2)
    return keyboard.as_markup()


def back_menu():
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="⬅️ В главное меню", callback_data="vortex:home")
    return keyboard.as_markup()


MENU_TEXT = {
    "moderation": (
        "🛡 <b>Модерация</b>\n\n"
        "Ответь на сообщение участника одной из команд:\n"
        "/mute 10m — ограничить на 10 минут\n"
        "/unmute — снять ограничение\n"
        "/kick — удалить из группы\n"
        "/ban — заблокировать\n"
        "/unban ID — снять блокировку по Telegram ID"
    ),
    "warnings": (
        "⚠️ <b>Предупреждения</b>\n\n"
        "Ответь на сообщение участника:\n"
        "/warn — выдать предупреждение\n"
        "/warnings — посмотреть количество\n"
        "/clearwarns — очистить предупреждения"
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
        "/stats — статистика группы"
    ),
}


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


@router.callback_query(lambda query: query.data and query.data.startswith("vortex:"))
async def menu_callback(query: CallbackQuery):
    section = query.data.split(":", 1)[1]
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
