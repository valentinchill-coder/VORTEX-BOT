from html import escape

from aiogram import Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message

from database.db import Database

router = Router()


@router.message(Command("balance"))
async def balance_command(message: Message, db: Database):
    if message.chat.type == ChatType.PRIVATE:
        await message.answer("Баланс доступен в группе.")
        return
    target = message.reply_to_message.from_user if message.reply_to_message else message.from_user
    if not target:
        await message.answer("Не удалось определить участника.")
        return
    balance = await db.get_balance(message.chat.id, target.id)
    await message.answer(f"💰 Баланс {escape(target.full_name)}: <b>{balance} V-coins</b>")


@router.message(Command("daily"))
async def daily_command(message: Message, db: Database):
    if message.chat.type == ChatType.PRIVATE:
        await message.answer("Ежедневную награду можно получить в группе.")
        return
    if not message.from_user:
        return
    claimed, balance = await db.claim_daily(message.chat.id, message.from_user.id)
    if claimed:
        await message.answer(
            f"🎁 Ты получил ежедневную награду: <b>+100 V-coins</b>!\n"
            f"Текущий баланс: <b>{balance} V-coins</b>"
        )
    else:
        await message.answer(
            f"⏳ Ежедневная награда уже получена.\n"
            f"Текущий баланс: <b>{balance} V-coins</b>"
        )


@router.message(Command("pay"))
async def pay_command(message: Message, db: Database):
    if message.chat.type == ChatType.PRIVATE:
        await message.answer("Переводы доступны только в группе.")
        return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.answer("Ответь командой /pay 50 на сообщение получателя.")
        return
    if not message.from_user:
        return
    target = message.reply_to_message.from_user
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Укажи сумму: /pay 50")
        return
    amount = int(parts[1])
    if amount < 1 or amount > 1_000_000:
        await message.answer("Сумма должна быть от 1 до 1 000 000 V-coins.")
        return
    if target.is_bot or target.id == message.from_user.id:
        await message.answer("Нельзя переводить монеты себе или ботам.")
        return
    success, sender_balance = await db.transfer(
        message.chat.id, message.from_user.id, target.id, amount
    )
    if not success:
        await message.answer(f"Недостаточно средств. Твой баланс: {sender_balance} V-coins.")
        return
    await message.answer(
        f"💸 {escape(message.from_user.full_name)} перевёл "
        f"{escape(target.full_name)} <b>{amount} V-coins</b>.\n"
        f"Остаток: <b>{sender_balance} V-coins</b>"
    )


@router.message(Command("topmoney"))
async def top_money_command(message: Message, db: Database):
    if message.chat.type == ChatType.PRIVATE:
        await message.answer("Рейтинг доступен в группе.")
        return
    leaders = await db.top_balances(message.chat.id)
    if not leaders:
        await message.answer("Пока в рейтинге нет участников. Используй /daily, чтобы получить первые монеты.")
        return
    lines = ["💰 <b>Топ богачей VORTEX</b>", ""]
    for index, (user_id, balance) in enumerate(leaders, start=1):
        try:
            member = await message.bot.get_chat_member(message.chat.id, user_id)
            name = escape(member.user.full_name)
        except Exception:
            name = f"Участник {user_id}"
        lines.append(f"{index}. {name} — <b>{balance}</b> V-coins")
    await message.answer("\n".join(lines))


@router.message(Command("exchange"))
async def exchange_command(message: Message, db: Database):
    if message.chat.type == ChatType.PRIVATE:
        await message.answer("Обмен игровых очков на V-coins доступен только в группе.")
        return
    if not message.from_user:
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer(
            "Укажи количество игровых очков: /exchange 100\n"
            "Курс: 10 игровых очков = 1 V-coin. Сумма должна быть кратна 10."
        )
        return
    points = int(parts[1])
    if points < 10 or points > 1_000_000:
        await message.answer("Можно обменять от 10 до 1 000 000 игровых очков за раз.")
        return
    if points % 10:
        await message.answer("Количество очков должно быть кратно 10. Например: /exchange 100")
        return
    success, remaining_points, balance, coins = await db.exchange_game_points(
        message.chat.id, message.from_user.id, points, rate=10
    )
    if not success:
        await message.answer(
            f"Недостаточно игровых очков. Сейчас у тебя: <b>{remaining_points}</b>."
        )
        return
    await message.answer(
        f"💱 Обмен выполнен!\n"
        f"Списано: <b>{points}</b> игровых очков\n"
        f"Начислено: <b>+{coins} V-coins</b>\n"
        f"Остаток игровых очков: <b>{remaining_points}</b>\n"
        f"Баланс: <b>{balance} V-coins</b>"
    )


# Interactive economy controls: no slash commands required.
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

_economy_pending: dict[tuple[int, int], str] = {}

def economy_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="💰 Мой баланс", callback_data="eco:balance")
    kb.button(text="🎁 Забрать ежедневные 100", callback_data="eco:daily")
    kb.button(text="💸 Перевести монеты", callback_data="eco:transfer")
    kb.button(text="💱 Обменять игровые очки", callback_data="eco:exchange")
    kb.button(text="🏆 Топ богачей", callback_data="eco:top")
    kb.button(text="⬅️ Главное меню", callback_data="vortex:home")
    kb.adjust(1)
    return kb.as_markup()

@router.callback_query(lambda q: q.data and q.data.startswith("eco:"))
async def economy_button_callback(query: CallbackQuery, db: Database):
    if not query.message or not query.from_user:
        await query.answer()
        return
    if query.message.chat.type == ChatType.PRIVATE:
        await query.answer("Экономика работает в группе.", show_alert=True)
        return
    action = query.data.split(":", 1)[1]
    chat_id, user_id = query.message.chat.id, query.from_user.id
    if action == "balance":
        balance = await db.get_balance(chat_id, user_id)
        await query.message.answer(f"💰 Твой баланс: <b>{balance} V-coins</b>")
    elif action == "daily":
        claimed, balance = await db.claim_daily(chat_id, user_id)
        if claimed:
            result = f"🎁 Начислено +100 V-coins! Баланс: <b>{balance}</b>."
        else:
            result = f"⏳ Сегодня награда уже получена. Баланс: <b>{balance}</b>."
        await query.message.answer(result)
    elif action == "transfer":
        _economy_pending[(chat_id, user_id)] = "transfer"
        await query.message.answer(
            "💸 Чтобы перевести монеты, отправь сумму обычным сообщением в ответ на сообщение получателя. "
            "Например, ответь числом <code>50</code>."
        )
    elif action == "exchange":
        _economy_pending[(chat_id, user_id)] = "exchange"
        await query.message.answer(
            "💱 Сколько игровых очков обменять? Отправь число обычным сообщением. "
            "Курс: 10 игровых очков = 1 V-coin; сумма должна делиться на 10."
        )
    elif action == "top":
        leaders = await db.top_balances(chat_id)
        lines = ["🏆 <b>Топ богачей VORTEX</b>", ""]
        for i, (uid, amount) in enumerate(leaders, 1):
            try:
                member = await query.bot.get_chat_member(chat_id, uid)
                name = escape(member.user.full_name)
            except Exception:
                name = f"Участник {uid}"
            lines.append(f"{i}. {name} — <b>{amount}</b> V-coins")
        await query.message.answer("\\n".join(lines) if leaders else "Пока рейтинг пуст.")
    else:
        await query.answer("Неизвестное действие.", show_alert=True)
        return
    await query.answer()

@router.message(lambda m: m.from_user is not None and m.chat.type != ChatType.PRIVATE
                and (m.chat.id, m.from_user.id) in _economy_pending
                and not (m.text or "").startswith("/"))
async def economy_plain_input(message: Message, db: Database):
    if not message.from_user:
        return
    key = (message.chat.id, message.from_user.id)
    action = _economy_pending.get(key)
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Отправь сумму целым положительным числом.")
        return
    amount = int(raw)
    if action == "exchange":
        if amount < 10 or amount > 1_000_000 or amount % 10:
            await message.answer("Укажи от 10 до 1 000 000 очков, кратно 10.")
            return
        success, remaining, balance, coins = await db.exchange_game_points(message.chat.id, message.from_user.id, amount, rate=10)
        if not success:
            await message.answer(f"Недостаточно игровых очков. Сейчас: {remaining}.")
            return
        _economy_pending.pop(key, None)
        await message.answer(
            f"✅ Обмен выполнен: списано {amount} очков, начислено +{coins} V-coins. "
            f"Остаток очков: {remaining}; баланс: {balance}."
        )
        return
    if action == "transfer":
        if not message.reply_to_message or not message.reply_to_message.from_user:
            await message.answer("Для перевода отправь сумму ответом на сообщение получателя.")
            return
        target = message.reply_to_message.from_user
        if target.is_bot or target.id == message.from_user.id:
            await message.answer("Нельзя переводить монеты себе или ботам.")
            return
        if not 1 <= amount <= 1_000_000:
            await message.answer("Сумма должна быть от 1 до 1 000 000 V-coins.")
            return
        success, balance = await db.transfer(message.chat.id, message.from_user.id, target.id, amount)
        if not success:
            await message.answer(f"Недостаточно средств. Баланс: {balance} V-coins.")
            return
        _economy_pending.pop(key, None)
        await message.answer(
            f"💸 Перевод выполнен: {escape(target.full_name)} получил {amount} V-coins. "
            f"Твой остаток: {balance}."
        )
