from aiogram import Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message

from database.db import Database

router = Router()

DAILY_QUESTS = (
    ("messages_10", "Активный участник", "messages", 10, 10, "Напиши 10 сообщений в группе"),
    ("games_3", "Игровой вечер", "games", 3, 15, "Сыграй 3 партии"),
    ("win_1", "Первая победа дня", "wins", 1, 10, "Одержи 1 победу"),
)


def _quest_text(progress: dict[str, int]) -> str:
    lines = ["📜 <b>Ежедневные задания VORTEX</b>", ""]
    total_reward = 0
    for quest_id, title, metric, target, reward, description in DAILY_QUESTS:
        value = progress.get(metric, 0)
        if value >= target:
            state = "✅ Выполнено"
            total_reward += reward
        else:
            state = f"⏳ {value}/{target}"
        lines.append(f"<b>{title}</b> — {state}\n{description} · награда: {reward} V-coins")
    lines.extend([
        "",
        f"Доступно за выполнение: <b>до {total_reward if total_reward else sum(q[4] for q in DAILY_QUESTS)} V-coins</b>",
        "Забрать готовые награды: <code>/claimquests</code>",
        "Прогресс обновляется после обычных сообщений и завершённых игр.",
    ])
    return "\n".join(lines)


@router.message(Command("quests"))
async def quests_command(message: Message, db: Database):
    if message.chat.type == ChatType.PRIVATE or not message.from_user:
        await message.answer("Ежедневные задания доступны в группе.")
        return
    progress = await db.daily_quest_progress(message.chat.id, message.from_user.id)
    await message.answer(_quest_text(progress))


@router.message(Command("claimquests"))
async def claim_quests_command(message: Message, db: Database):
    if message.chat.type == ChatType.PRIVATE or not message.from_user:
        await message.answer("Забирать награды за задания можно в группе.")
        return
    rules = [(quest_id, metric, target, reward)
             for quest_id, _title, metric, target, reward, _description in DAILY_QUESTS]
    claimed, balance = await db.claim_daily_quest_rewards(
        message.chat.id, message.from_user.id, rules
    )
    if not claimed:
        await message.answer(
            f"Пока нет новых выполненных заданий для получения награды. Баланс: {balance} V-coins. "
            "Посмотреть прогресс: /quests"
        )
        return
    titles = {quest_id: title for quest_id, title, *_ in DAILY_QUESTS}
    reward_total = sum(
        reward for quest_id, _title, _metric, _target, reward, _description in DAILY_QUESTS
        if quest_id in claimed
    )
    lines = ["🎁 <b>Награды получены!</b>"]
    lines.extend(f"• {titles[quest_id]}" for quest_id in claimed)
    lines.append(f"\nНачислено: <b>+{reward_total} V-coins</b>")
    lines.append(f"Баланс: <b>{balance} V-coins</b>")
    await message.answer("\n".join(lines))
