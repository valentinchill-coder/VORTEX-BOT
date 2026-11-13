from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command("start"))
async def start_command(message: Message):
    await message.answer(
        "🌪 <b>VORTEX BOT</b> запущен.\n\n"
        "Я помогаю администраторам управлять группой: модерация, "
        "предупреждения и защита от флуда.\n"
        "Команда /help покажет доступные команды.",
        parse_mode="HTML",
    )


@router.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        "<b>Команды VORTEX BOT</b>\n"
        "/help — помощь\n"
        "/warn — предупреждение (ответом на сообщение)\n"
        "/warnings — число предупреждений (ответом)\n"
        "/clearwarns — очистить предупреждения (ответом)\n"
        "/mute 10m — ограничить пользователя (ответом)\n"
        "/unmute — снять ограничение (ответом)\n"
        "/kick — удалить из группы (ответом)\n"
        "/ban — заблокировать (ответом)\n"
        "/unban ID — разблокировать по Telegram ID\n"
        "/stats — статистика группы\n\n"
        "Команды модерации доступны только администраторам.",
        parse_mode="HTML",
    )
