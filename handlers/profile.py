from html import escape

from aiogram import Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message

from database.db import Database

router = Router()


def _rank(messages: int) -> str:
    if messages >= 1000:
        return "🌪 Легенда"
    if messages >= 500:
        return "💎 Ветеран"
    if messages >= 150:
        return "🔥 Активный"
    if messages >= 30:
        return "⭐ Участник"
    return "🌱 Новичок"


@router.message(Command("profile"))
async def profile_command(message: Message, db: Database):
    if message.chat.type == ChatType.PRIVATE:
        await message.answer("Открой команду /profile в группе, чтобы посмотреть профиль.")
        return
    target = message.reply_to_message.from_user if message.reply_to_message else message.from_user
    if not target:
        await message.answer("Не удалось определить участника.")
        return
    data = await db.get_profile(message.chat.id, target.id)
    user = data["user"]
    name = escape(target.full_name)
    username = f"@{escape(target.username)}" if target.username else "не указан"
    messages = user["message_count"] if user else 0
    rank = _rank(messages)
    first_seen = user["first_seen"][:10] if user else "пока нет данных"
    await message.answer(
        f"👤 <b>Профиль участника</b>\n\n"
        f"Имя: <b>{name}</b>\n"
        f"Username: {username}\n"
        f"Ранг: {rank}\n"
        f"Сообщений: <b>{messages}</b>\n"
        f"Репутация: <b>{data['reputation']}</b>\n"
        f"Предупреждений: <b>{data['warnings']}</b>\n"
        f"В чате с: {first_seen}"
    )


@router.message(Command("rep"))
async def reputation_command(message: Message, db: Database):
    if message.chat.type == ChatType.PRIVATE:
        await message.answer("Репутацию можно выдавать только в группе.")
        return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.answer("Ответь командой /rep на сообщение участника.")
        return
    target = message.reply_to_message.from_user
    giver = message.from_user
    if not giver:
        return
    if target.is_bot or target.id == giver.id:
        await message.answer("Нельзя выдавать репутацию самому себе или ботам.")
        return
    granted = await db.give_reputation(message.chat.id, target.id, giver.id)
    if not granted:
        await message.answer("Ты уже выдавал этому участнику репутацию сегодня. Попробуй завтра.")
        return
    await message.answer(f"⭐ {escape(target.full_name)} получил +1 к репутации!")


@router.message(Command("toprep"))
async def top_reputation_command(message: Message, db: Database):
    if message.chat.type == ChatType.PRIVATE:
        await message.answer("Рейтинг репутации доступен в группе.")
        return
    leaders = await db.top_reputation(message.chat.id)
    if not leaders:
        await message.answer("Пока рейтинг пуст. Выдать репутацию можно командой /rep ответом на сообщение.")
        return
    lines = ["🏆 <b>Топ репутации</b>", ""]
    for index, (user_id, score) in enumerate(leaders, start=1):
        try:
            member = await message.bot.get_chat_member(message.chat.id, user_id)
            name = escape(member.user.full_name)
        except Exception:
            name = f"Участник {user_id}"
        lines.append(f"{index}. {name} — <b>{score}</b> ⭐")
    await message.answer("\n".join(lines))


@router.message(Command("topactivity"))
async def top_activity_command(message: Message, db: Database):
    if message.chat.type == ChatType.PRIVATE:
        await message.answer("Рейтинг активности доступен в группе.")
        return
    leaders = await db.top_activity(message.chat.id)
    if not leaders:
        await message.answer("Пока нет данных об активности. Они начнут собираться с этого момента.")
        return
    lines = ["📈 <b>Топ активности группы</b>", ""]
    for index, (user_id, messages) in enumerate(leaders, start=1):
        try:
            member = await message.bot.get_chat_member(message.chat.id, user_id)
            name = escape(member.user.full_name)
        except Exception:
            name = f"Участник {user_id}"
        lines.append(f"{index}. {name} — <b>{messages}</b> сообщений")
    await message.answer("\\n".join(lines))
