import os
import tempfile
from datetime import datetime, timezone

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message

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


@router.message(Command("backup"))
async def backup_command(message: Message, db: Database, owner_ids: frozenset[int]):
    if not message.from_user or message.from_user.id not in owner_ids:
        await message.answer("Создавать резервную копию может только владелец VORTEX.")
        return
    if message.chat.type != "private":
        await message.answer("Для безопасности запроси резервную копию в личном чате с ботом.")
        return

    file_descriptor, backup_path = tempfile.mkstemp(prefix="vortex-backup-", suffix=".db")
    os.close(file_descriptor)
    try:
        await db.backup_to(backup_path)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        await message.answer_document(
            FSInputFile(backup_path, filename=f"vortex-backup-{stamp}.db"),
            caption="Резервная копия базы VORTEX. Сохрани файл в надёжном месте.",
        )
    finally:
        try:
            os.remove(backup_path)
        except FileNotFoundError:
            pass
