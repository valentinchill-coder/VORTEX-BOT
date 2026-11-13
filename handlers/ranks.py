from html import escape

from aiogram import Bot, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import Message

from database.db import Database

router = Router()

RANKS = {
    0: ("Участник", "Без прав модерации"),
    1: ("Стажёр", "Просмотр предупреждений и наблюдение"),
    2: ("Младший модератор", "Предупреждения и просмотр истории"),
    3: ("Модератор", "Предупреждения, мут и снятие мута"),
    4: ("Старший модератор", "Все права модератора, кик и бан"),
    5: ("Главный модератор", "Управление младшими рангами"),
    6: ("Администратор", "Полное управление модерацией группы"),
    7: ("Владелец VORTEX", "Полные права владельца бота"),
}

ACTION_RANK = {
    "warnings": 1, "warn": 2, "clearwarns": 3, "mute": 3,
    "unmute": 3, "kick": 4, "ban": 4, "unban": 4, "audit": 5,
}

async def get_rank(db: Database, bot: Bot, chat_id: int, user_id: int,
                   owner_ids: frozenset[int]) -> int:
    if user_id in owner_ids:
        return 7
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        if member.status in (ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR):
            return 6
    except TelegramAPIError:
        pass
    return await db.get_moderation_rank(chat_id, user_id)

async def can_action(db: Database, bot: Bot, chat_id: int, user_id: int,
                     action: str, owner_ids: frozenset[int]) -> bool:
    needed = ACTION_RANK.get(action)
    return needed is not None and await get_rank(db, bot, chat_id, user_id, owner_ids) >= needed

async def rank_denial(message: Message, db: Database, bot: Bot,
                      owner_ids: frozenset[int], action: str) -> bool:
    if not message.from_user or message.chat.type == "private":
        await message.answer("Эта функция доступна только в группе.")
        return False
    if await can_action(db, bot, message.chat.id, message.from_user.id, action, owner_ids):
        return True
    needed = ACTION_RANK.get(action, 99)
    name = RANKS[needed][0] if needed in RANKS else "нужный ранг"
    await message.answer(f"Недостаточно прав. Для этого действия нужен ранг «{name}» или выше.")
    return False


async def handle_natural_rank(message: Message, db: Database, bot: Bot,
                              owner_ids: frozenset[int], intent: str) -> None:
    """Handle conversational rank requests while enforcing the same hierarchy as /setrank."""
    if not message.from_user or message.chat.type == "private":
        await message.answer("Управление рангами доступно только в группе.")
        return
    if intent == "__rank_usage__":
        await message.answer("Чтобы выдать ранг, ответь на сообщение участника фразой «Выдать ранг 2». Для повышения или понижения достаточно написать «Повысить» или «Понизить» ответом на его сообщение. «Снять ранг» убирает назначенный ранг.")
        return
    if intent == "__myrank__":
        rank = await get_rank(db, bot, message.chat.id, message.from_user.id, owner_ids)
        name, description = RANKS[rank]
        await message.answer(f"Твой ранг: <b>{name}</b> ({rank}/7)\n{description}")
        return
    if intent == "__ranks__":
        lines = ["🛡 <b>Иерархия модерации VORTEX</b>"]
        for number, (name, description) in RANKS.items():
            lines.append(f"<b>{number}. {name}</b> — {description}")
        lines.append("\nРанг 6 автоматически получают администраторы Telegram. Ранг 7 — владелец бота.")
        await message.answer("\n".join(lines))
        return

    actor_rank = await get_rank(db, bot, message.chat.id, message.from_user.id, owner_ids)
    if actor_rank < 5:
        await message.answer("Изменять ранги может Главный модератор или Администратор группы.")
        return
    target_message = message.reply_to_message
    if not target_message or not target_message.from_user:
        await message.answer("Ответь этой фразой на сообщение участника, чей ранг нужно изменить.")
        return
    target = target_message.from_user
    if target.is_bot or target.id == message.from_user.id:
        await message.answer("Нельзя менять ранг боту или самому себе.")
        return
    current = await get_rank(db, bot, message.chat.id, target.id, owner_ids)
    if current >= actor_rank:
        await message.answer("Нельзя менять ранг равного или старшего по иерархии.")
        return

    if intent == "__rank_remove__":
        new_rank = 0
    elif intent == "__rank_up__":
        new_rank = min(current + 1, 5)
    elif intent == "__rank_down__":
        new_rank = max(current - 1, 0)
    else:
        new_rank = int(intent.removeprefix("__rank_set_").removesuffix("__"))

    if not 0 <= new_rank <= 5:
        await message.answer("Доступны ранги от 1 до 5; 0 снимает ранг. Ранги 6 и 7 назначаются автоматически.")
        return
    if new_rank >= actor_rank:
        await message.answer("Нельзя выдавать ранг, равный вашему или выше.")
        return
    if actor_rank == 5 and new_rank > 3:
        await message.answer("Главный модератор может назначать только ранги 1–3.")
        return
    if new_rank == current:
        await message.answer("У участника уже этот ранг.")
        return

    await db.set_moderation_rank(message.chat.id, target.id, new_rank, message.from_user.id)
    await db.log_moderation_action(
        message.chat.id, message.from_user.id, target.id,
        "rank_change", f"{current} -> {new_rank}",
    )
    if new_rank == 0:
        await message.answer(f"Ранг пользователя {escape(target.full_name)} снят.")
    else:
        await message.answer(f"Пользователь {escape(target.full_name)}: ранг «{RANKS[new_rank][0]}» ({new_rank}/7).")

@router.message(Command("ranks"))
async def ranks_command(message: Message):
    lines = ["🛡 <b>Иерархия модерации VORTEX</b>"]
    for number, (name, description) in RANKS.items():
        lines.append(f"<b>{number}. {name}</b> — {description}")
    lines.append("\nРанг 6 автоматически получают администраторы Telegram. Ранг 7 — владелец бота из OWNER_IDS.")
    await message.answer("\n".join(lines))

@router.message(Command("myrank"))
async def myrank_command(message: Message, db: Database, bot: Bot,
                         owner_ids: frozenset[int]):
    if not message.from_user or message.chat.type == "private":
        await message.answer("Команда работает в группе.")
        return
    rank = await get_rank(db, bot, message.chat.id, message.from_user.id, owner_ids)
    name, description = RANKS[rank]
    await message.answer(f"Твой ранг: <b>{name}</b> ({rank}/7)\n{description}")

@router.message(Command("setrank"))
async def setrank_command(message: Message, db: Database, bot: Bot,
                          owner_ids: frozenset[int]):
    if not message.from_user or message.chat.type == "private":
        await message.answer("Команда работает в группе.")
        return
    actor_rank = await get_rank(db, bot, message.chat.id, message.from_user.id, owner_ids)
    if actor_rank < 5:
        await message.answer("Выдавать ранги может Главный модератор или Администратор группы.")
        return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.answer("Ответь командой /setrank 1 на сообщение участника. Для снятия ранга: /setrank 0.")
        return
    target = message.reply_to_message.from_user
    if target.is_bot or target.id == message.from_user.id:
        await message.answer("Нельзя назначить ранг боту или самому себе.")
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Укажи ранг от 1 до 5, либо 0 для снятия.")
        return
    new_rank = int(parts[1])
    if not 0 <= new_rank <= 5:
        await message.answer("Доступны ранги 1–5. Ранги 6 и 7 назначаются автоматически.")
        return
    target_rank = await get_rank(db, bot, message.chat.id, target.id, owner_ids)
    if target_rank >= actor_rank:
        await message.answer("Нельзя менять ранг равного или старшего по иерархии.")
        return
    if new_rank >= actor_rank:
        await message.answer("Нельзя выдавать ранг, равный вашему или выше.")
        return
    if actor_rank == 5 and new_rank > 3:
        await message.answer("Главный модератор может назначать только ранги 1–3.")
        return
    await db.set_moderation_rank(message.chat.id, target.id, new_rank, message.from_user.id)
    await db.log_moderation_action(
        message.chat.id, message.from_user.id, target.id,
        "rank_change", f"{target_rank} -> {new_rank}",
    )
    if new_rank == 0:
        await message.answer(f"Ранг пользователя {escape(target.full_name)} снят.")
    else:
        await message.answer(f"Пользователю {escape(target.full_name)} назначен ранг «{RANKS[new_rank][0]}».")
