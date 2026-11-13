from html import escape

from aiogram import Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message

from database.db import Database
from handlers.ranks import get_rank, RANKS

router = Router()


ACHIEVEMENTS = (
    ("Первые шаги", "messages", 1, "Напиши первое сообщение в группе"),
    ("Голос группы", "messages", 100, "Отправь 100 сообщений"),
    ("Легенда чата", "messages", 1000, "Отправь 1 000 сообщений"),
    ("Первая победа", "wins", 1, "Одержи первую победу в игре"),
    ("Чемпион", "wins", 10, "Одержи 10 побед"),
    ("Опытный игрок", "played", 25, "Сыграй 25 партий"),
    ("Уважаемый", "reputation", 10, "Получи 10 очков репутации"),
    ("Коллекционер", "items", 10, "Собери 10 предметов"),
    ("Богач", "balance", 1000, "Накопи 1 000 V-coins"),
)


def _achievement_text(stats: dict[str, int]) -> str:
    lines = ["🏅 <b>Достижения VORTEX</b>", ""]
    unlocked = 0
    for name, key, target, description in ACHIEVEMENTS:
        value = stats.get(key, 0)
        if value >= target:
            unlocked += 1
            lines.append(f"🏆 <b>{name}</b> — получено")
        else:
            lines.append(f"🔒 <b>{name}</b> — {value}/{target} · {description}")
    lines.extend(["", f"Открыто достижений: <b>{unlocked}/{len(ACHIEVEMENTS)}</b>"])
    return "\n".join(lines)


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
async def profile_command(message: Message, db: Database, owner_ids: frozenset[int]):
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
    moderation_rank = await get_rank(db, message.bot, message.chat.id, target.id, owner_ids)
    first_seen = user["first_seen"][:10] if user else "пока нет данных"
    await message.answer(
        f"👤 <b>Профиль участника</b>\n\n"
        f"Имя: <b>{name}</b>\n"
        f"Username: {username}\n"
        f"Ранг активности: {rank}\n"
        f"Ранг модерации: <b>{RANKS[moderation_rank][0]}</b>\n"
        f"Сообщений: <b>{messages}</b>\n"
        f"Репутация: <b>{data['reputation']}</b>\n"
        f"Предупреждений: <b>{data['warnings']}</b>\n"
        f"В чате с: {first_seen}"
    )


@router.message(Command("achievements"))
async def achievements_command(message: Message, db: Database):
    if message.chat.type == ChatType.PRIVATE or not message.from_user:
        await message.answer("Достижения доступны в группе.")
        return
    stats = await db.achievement_stats(message.chat.id, message.from_user.id)
    await message.answer(_achievement_text(stats))


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
    await message.answer("\n".join(lines))


# Profile and reputation menu buttons.
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

_profile_pending_rep: set[tuple[int, int]] = set()

def profile_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="👤 Мой профиль", callback_data="profile:me")
    kb.button(text="⭐ Топ репутации", callback_data="profile:toprep")
    kb.button(text="📈 Топ активности", callback_data="profile:topactivity")
    kb.button(text="🏅 Мои достижения", callback_data="profile:achievements")
    kb.button(text="⭐ Выдать репутацию", callback_data="profile:give")
    kb.button(text="⬅️ Главное меню", callback_data="vortex:home")
    kb.adjust(1)
    return kb.as_markup()

@router.callback_query(lambda q: q.data and q.data.startswith("profile:"))
async def profile_button_callback(query: CallbackQuery, db: Database, owner_ids: frozenset[int]):
    if not query.message or not query.from_user:
        await query.answer()
        return
    if query.message.chat.type == ChatType.PRIVATE:
        await query.answer("Профили доступны в группе.", show_alert=True)
        return
    action = query.data.split(":", 1)[1]
    if action == "give":
        _profile_pending_rep.add((query.message.chat.id, query.from_user.id))
        await query.message.answer("⭐ Чтобы выдать +1 репутацию, ответь любым сообщением на сообщение участника.")
    elif action == "achievements":
        stats = await db.achievement_stats(query.message.chat.id, query.from_user.id)
        await query.message.answer(_achievement_text(stats))
    elif action == "me":
        data = await db.get_profile(query.message.chat.id, query.from_user.id)
        user = data["user"] or {}
        messages = int(user.get("message_count", 0))
        username = f"@{escape(query.from_user.username)}" if query.from_user.username else "не указан"
        moderation_rank = await get_rank(db, query.bot, query.message.chat.id, query.from_user.id, owner_ids)
        first_seen = user.get("first_seen", "пока нет данных")[:10]
        await query.message.answer(
            f"👤 <b>Твой профиль</b>\n\nИмя: <b>{escape(query.from_user.full_name)}</b>\n"
            f"Username: {username}\nРанг активности: {_rank(messages)}\n"
            f"Ранг модерации: <b>{RANKS[moderation_rank][0]}</b>\nСообщений: <b>{messages}</b>\n"
            f"Репутация: <b>{data['reputation']}</b>\nПредупреждений: <b>{data['warnings']}</b>\n"
            f"В чате с: {first_seen}"
        )
    elif action in ("toprep", "topactivity"):
        rows = await (db.top_reputation(query.message.chat.id) if action == "toprep"
                      else db.top_activity(query.message.chat.id))
        lines = ["🏆 <b>Топ репутации</b>" if action == "toprep" else "📈 <b>Топ активности</b>", ""]
        for i, (uid, score) in enumerate(rows, 1):
            try:
                member = await query.bot.get_chat_member(query.message.chat.id, uid)
                name = escape(member.user.full_name)
            except Exception:
                name = f"Участник {uid}"
            suffix = "⭐" if action == "toprep" else "сообщений"
            lines.append(f"{i}. {name} — <b>{score}</b> {suffix}")
        await query.message.answer("\n".join(lines) if rows else "Пока данных нет.")
    await query.answer()

@router.message(Command("cancel"), lambda m: m.from_user is not None and m.chat.type != ChatType.PRIVATE
                and (m.chat.id, m.from_user.id) in _profile_pending_rep)
async def cancel_reputation_action(message: Message):
    if message.from_user:
        _profile_pending_rep.discard((message.chat.id, message.from_user.id))
    await message.answer("Выдача репутации отменена.")


@router.message(lambda m: m.from_user is not None and m.chat.type != ChatType.PRIVATE
                and (m.chat.id, m.from_user.id) in _profile_pending_rep
                and not (m.text or "").startswith("/"))
async def give_reputation_plain(message: Message, db: Database):
    if not message.from_user:
        return
    target_message = message.reply_to_message
    if not target_message or not target_message.from_user:
        await message.answer("Ответь на сообщение того, кому хочешь выдать репутацию.")
        return
    target, giver = target_message.from_user, message.from_user
    if target.is_bot or target.id == giver.id:
        await message.answer("Нельзя выдавать репутацию себе или ботам.")
        return
    granted = await db.give_reputation(message.chat.id, target.id, giver.id)
    if granted:
        _profile_pending_rep.discard((message.chat.id, giver.id))
        await message.answer(f"⭐ {escape(target.full_name)} получил +1 к репутации!")
    else:
        _profile_pending_rep.discard((message.chat.id, giver.id))
        await message.answer("Ты уже выдавал этому участнику репутацию сегодня.")
