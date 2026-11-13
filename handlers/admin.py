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
    data = await db.chat_stats(message.chat.id)
    await message.answer(
        "📊 <b>Статистика VORTEX BOT</b>\n\n"
        f"Участников с активностью: <b>{data['users']}</b>\n"
        f"Сообщений учтено: <b>{data['messages']}</b>\n"
        f"Предупреждений выдано: <b>{data['warnings']}</b>\n"
        f"Срабатываний антифлуда: <b>{data['antiflood']}</b>"
    )
