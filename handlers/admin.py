from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from database.db import Database

router = Router()


@router.message(Command("stats"))
async def stats(message: Message, db: Database):
    if message.chat.type == "private":
        await message.answer("Статистика доступна в группе.")
        return
    warnings = await db.event_count(message.chat.id, "warn")
    await message.answer(
        "📊 <b>Статистика VORTEX BOT</b>\n"
        f"Предупреждений выдано: {warnings}",
        parse_mode="HTML",
    )
