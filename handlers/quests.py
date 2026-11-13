from aiogram import Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.db import Database

router = Router()

DAILY_QUESTS = (
    ("messages_10", "Активный участник", "messages", 10, 10, "Напиши 10 сообщений в группе"),
    ("games_3", "Игровой вечер", "games", 3, 15, "Сыграй 3 партии"),
    ("win_1", "Первая победа дня", "wins", 1, 10, "Одержи 1 победу"),
)


def format_quests(progress: dict[str, int]) -> str:
    lines = ["📜 <b>Ежедневные задания VORTEX</b>", ""]
    available_reward = 0
    for _quest_id, title, metric, target, reward, description in DAILY_QUESTS:
        value = progress.get(metric, 0)
        if value >= target:
            state = "✅ Выполнено"
            available_reward += reward
        else:
            state = f"⏳ {value}/{target}"
        lines.append(f"<b>{title}</b> — {state}\n{description} · награда: {reward} V-coins")
    lines.extend([
        "",
        f"Награда за уже выполненные задания: <b>{available_reward} V-coins</b>",
        "Прогресс обновляется после обычных сообщений и завершённых игр.",
    ])
    return "\n".join(lines)


def quest_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🎁 Забрать награды", callback_data="quests:claim")
    kb.button(text="🔄 Обновить задания", callback_data="quests:show")
    kb.button(text="⬅️ Главное меню", callback_data="vortex:home")
    kb.adjust(1)
    return kb.as_markup()


async def _safe_query_answer(query: CallbackQuery, *args, **kwargs) -> None:
    try:
        await query.answer(*args, **kwargs)
    except TelegramBadRequest as exc:
        message = exc.message.lower()
        if "query is too old" not in message and "query id is invalid" not in message:
            raise


def _quest_rules() -> list[tuple[str, str, int, int]]:
    return [
        (quest_id, metric, target, reward)
        for quest_id, _title, metric, target, reward, _description in DAILY_QUESTS
    ]


async def _claim_rewards(db: Database, chat_id: int, user_id: int):
    claimed, balance = await db.claim_daily_quest_rewards(
        chat_id, user_id, _quest_rules()
    )
    titles = {quest_id: title for quest_id, title, *_ in DAILY_QUESTS}
    reward_total = sum(
        reward for quest_id, _title, _metric, _target, reward, _description in DAILY_QUESTS
        if quest_id in claimed
    )
    return claimed, balance, reward_total, titles


@router.message(Command("quests"))
async def quests_command(message: Message, db: Database):
    if message.chat.type == ChatType.PRIVATE or not message.from_user:
        await message.answer("Ежедневные задания доступны в группе.")
        return
    progress = await db.daily_quest_progress(message.chat.id, message.from_user.id)
    await message.answer(format_quests(progress), reply_markup=quest_keyboard())


@router.message(Command("claimquests"))
async def claim_quests_command(message: Message, db: Database):
    if message.chat.type == ChatType.PRIVATE or not message.from_user:
        await message.answer("Забирать награды за задания можно в группе.")
        return
    claimed, balance, reward_total, titles = await _claim_rewards(
        db, message.chat.id, message.from_user.id
    )
    if not claimed:
        await message.answer(
            f"Пока нет новых выполненных заданий для получения награды. Баланс: {balance} V-coins. "
            "Посмотреть прогресс: /quests",
            reply_markup=quest_keyboard(),
        )
        return
    lines = ["🎁 <b>Награды получены!</b>"]
    lines.extend(f"• {titles[quest_id]}" for quest_id in claimed)
    lines.append(f"\nНачислено: <b>+{reward_total} V-coins</b>")
    lines.append(f"Баланс: <b>{balance} V-coins</b>")
    await message.answer("\n".join(lines), reply_markup=quest_keyboard())


@router.callback_query(lambda q: q.data == "quests:show")
async def quests_show_callback(query: CallbackQuery, db: Database):
    if not query.message or not query.from_user:
        await _safe_query_answer(query)
        return
    if query.message.chat.type == ChatType.PRIVATE:
        await _safe_query_answer(query, "Задания доступны в группе.", show_alert=True)
        return
    progress = await db.daily_quest_progress(query.message.chat.id, query.from_user.id)
    await query.message.answer(format_quests(progress), reply_markup=quest_keyboard())
    await _safe_query_answer(query)


@router.callback_query(lambda q: q.data == "quests:claim")
async def quests_claim_callback(query: CallbackQuery, db: Database):
    if not query.message or not query.from_user:
        await _safe_query_answer(query)
        return
    if query.message.chat.type == ChatType.PRIVATE:
        await _safe_query_answer(query, "Задания доступны в группе.", show_alert=True)
        return
    claimed, balance, reward_total, titles = await _claim_rewards(
        db, query.message.chat.id, query.from_user.id
    )
    if not claimed:
        await query.message.answer(
            f"Пока нет новых наград. Баланс: {balance} V-coins.",
            reply_markup=quest_keyboard(),
        )
    else:
        lines = ["🎁 <b>Награды получены!</b>"]
        lines.extend(f"• {titles[quest_id]}" for quest_id in claimed)
        lines.append(f"\nНачислено: <b>+{reward_total} V-coins</b>")
        lines.append(f"Баланс: <b>{balance} V-coins</b>")
        await query.message.answer("\n".join(lines), reply_markup=quest_keyboard())
    await _safe_query_answer(query)
