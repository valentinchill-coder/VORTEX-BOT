import random
import secrets
from html import escape

from aiogram import Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.db import Database

router = Router()

GUESS_MIN = 1
GUESS_MAX = 63
GUESS_ATTEMPTS = 5

# Short-lived game rounds are kept in memory; long-term scores are stored in SQLite.
_guess_games: dict[tuple[int, int], dict[str, int]] = {}
_rps_rounds: dict[tuple[int, int], str] = {}
_quiz_rounds: dict[tuple[int, int], tuple[str, int]] = {}

_CHOICES = {"rock": "камень", "paper": "бумага", "scissors": "ножницы"}
_QUIZ = [
    ("Сколько планет в Солнечной системе?", ["6", "7", "8", "9"], 2),
    ("Как называется столица Японии?", ["Пекин", "Токио", "Сеул", "Бангкок"], 1),
    ("Сколько будет 12 × 8?", ["86", "92", "96", "108"], 2),
    ("Какой океан самый большой?", ["Атлантический", "Индийский", "Северный Ледовитый", "Тихий"], 3),
    ("Какой газ растения поглощают из воздуха?", ["Кислород", "Углекислый газ", "Азот", "Водород"], 1),
    ("Сколько сторон у шестиугольника?", ["5", "6", "7", "8"], 1),
    ("Какой металл обозначается символом Fe?", ["Медь", "Железо", "Серебро", "Золото"], 1),
    ("Как называется самая высокая гора Земли над уровнем моря?", ["Эльбрус", "Килиманджаро", "Эверест", "Монблан"], 2),
    ("Какой орган вырабатывает инсулин?", ["Печень", "Поджелудочная железа", "Почки", "Селезёнка"], 1),
    ("Какое число является простым?", ["21", "27", "29", "33"], 2),
    ("В каком году закончилась Вторая мировая война?", ["1943", "1944", "1945", "1946"], 2),
    ("Как называется переход вещества из твёрдого состояния сразу в газообразное?", ["Конденсация", "Сублимация", "Плавление", "Испарение"], 1),
    ("Какой язык программирования изначально создали для статистических вычислений?", ["R", "HTML", "CSS", "SQL"], 0),
    ("Как называется самая маленькая кость в теле человека?", ["Стремечко", "Молоточек", "Наковальня", "Надколенник"], 0),
    ("Какой химический элемент имеет атомный номер 8?", ["Азот", "Кислород", "Углерод", "Неон"], 1),
]


def games_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🔢 Угадай число", callback_data="game:start:guess")
    keyboard.button(text="✊ Камень, ножницы, бумага", callback_data="game:start:rps")
    keyboard.button(text="🧠 Викторина", callback_data="game:start:quiz")
    keyboard.button(text="🏆 Рейтинг игр", callback_data="game:top")
    keyboard.adjust(1)
    return keyboard.as_markup()


def _select_quiz_options(options: list[str], correct_index: int) -> tuple[list[str], int]:
    """Return one correct and one random incorrect answer, giving blind guesses 50/50 odds."""
    if not 0 <= correct_index < len(options) or len(options) < 2:
        raise ValueError("A quiz needs at least two options and a valid correct index.")
    correct_answer = options[correct_index]
    wrong_answer = random.choice([option for index, option in enumerate(options) if index != correct_index])
    displayed_options = [correct_answer, wrong_answer]
    random.shuffle(displayed_options)
    return displayed_options, displayed_options.index(correct_answer)


def _group_only(message: Message) -> bool:
    return message.chat.type != ChatType.PRIVATE


async def _start_guess(chat_id: int, user_id: int, send):
    key = (chat_id, user_id)
    if key in _guess_games:
        await send("У тебя уже идёт игра. Продолжай командой /guess число.")
        return
    number = random.randint(GUESS_MIN, GUESS_MAX)
    _guess_games[key] = {"number": number, "attempts": GUESS_ATTEMPTS}
    await send(
        "🔢 <b>Угадай число!</b>\n\n"
        "Я загадал число от 1 до 63. У тебя 5 попыток. Используй подсказки, чтобы сузить диапазон.\n"
        "Отправляй: <code>/guess 50</code>"
    )


async def _start_rps(chat_id: int, user_id: int, send):
    key = (chat_id, user_id)
    nonce = secrets.token_hex(3)
    _rps_rounds[key] = nonce
    keyboard = InlineKeyboardBuilder()
    for code, label in (("rock", "✊ Камень"), ("paper", "✋ Бумага"), ("scissors", "✌️ Ножницы")):
        keyboard.button(
            text=label,
            callback_data=f"game:rps:{user_id}:{nonce}:{code}",
        )
    keyboard.adjust(3)
    await send("✊ <b>Камень, ножницы, бумага!</b>\n\nВыбери свой ход:", reply_markup=keyboard.as_markup())


async def _start_quiz(chat_id: int, user_id: int, send):
    key = (chat_id, user_id)
    nonce = secrets.token_hex(3)
    question, options, correct_index = random.choice(_QUIZ)
    displayed_options, correct = _select_quiz_options(options, correct_index)
    _quiz_rounds[key] = (nonce, correct)
    keyboard = InlineKeyboardBuilder()
    for index, option in enumerate(displayed_options):
        keyboard.button(
            text=option,
            callback_data=f"game:quiz:{user_id}:{nonce}:{index}",
        )
    keyboard.adjust(2)
    await send(f"🧠 <b>Викторина</b>\n\n{escape(question)}\nВыбери правильный ответ из двух вариантов.", reply_markup=keyboard.as_markup())


@router.message(Command("games"))
async def games_command(message: Message):
    if not _group_only(message):
        await message.answer("Игры доступны в группе. Добавь бота в групповой чат.")
        return
    await message.answer(
        "🎮 <b>Игровой зал VORTEX</b>\n\n"
        "Выбирай игру. За победы начисляются игровые очки — они не списываются с твоих V-coins.",
        reply_markup=games_keyboard(),
    )


@router.message(Command("guessgame"))
async def guess_game_command(message: Message):
    if not _group_only(message):
        await message.answer("Играть можно в группе.")
        return
    if not message.from_user:
        return
    await _start_guess(message.chat.id, message.from_user.id, message.answer)


@router.message(Command("guess"))
async def guess_command(message: Message, db: Database):
    if not _group_only(message):
        await message.answer("Играть можно в группе.")
        return
    if not message.from_user:
        return
    key = (message.chat.id, message.from_user.id)
    game = _guess_games.get(key)
    if not game:
        await message.answer("Сначала начни игру: /guessgame")
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2:
        await message.answer(f"Напиши число от {GUESS_MIN} до {GUESS_MAX}: /guess 32")
        return
    try:
        guess = int(parts[1])
    except ValueError:
        await message.answer(f"Нужно указать целое число от {GUESS_MIN} до {GUESS_MAX}.")
        return
    if not GUESS_MIN <= guess <= GUESS_MAX:
        await message.answer(f"Число должно быть от {GUESS_MIN} до {GUESS_MAX}.")
        return

    game["attempts"] -= 1
    target = game["number"]
    if guess == target:
        _guess_games.pop(key, None)
        points, wins, played = await db.add_game_result(message.chat.id, message.from_user.id, 10, True)
        await message.answer(
            f"🎉 Верно! Загаданное число — <b>{target}</b>.\n"
            f"Ты получил <b>+10 игровых очков</b>.\n"
            f"Твой счёт: <b>{points}</b> | Побед: {wins}"
        )
    elif game["attempts"] == 0:
        _guess_games.pop(key, None)
        await db.add_game_result(message.chat.id, message.from_user.id, 0, False)
        await message.answer(f"Попытки закончились! Я загадал <b>{target}</b>. Начать заново: /guessgame")
    else:
        hint = "больше" if guess < target else "меньше"
        await message.answer(f"Не угадал. Моё число {hint}. Осталось попыток: <b>{game['attempts']}</b>.")


@router.callback_query(lambda query: query.data and query.data.startswith("game:start:"))
async def start_game_callback(query: CallbackQuery):
    if not query.message or not query.from_user:
        await query.answer()
        return
    if query.message.chat.type == ChatType.PRIVATE:
        await query.answer("Игры доступны в группах.", show_alert=True)
        return
    game = query.data.rsplit(":", 1)[-1]
    if game == "guess":
        await _start_guess(query.message.chat.id, query.from_user.id, query.message.answer)
    elif game == "rps":
        await _start_rps(query.message.chat.id, query.from_user.id, query.message.answer)
    elif game == "quiz":
        await _start_quiz(query.message.chat.id, query.from_user.id, query.message.answer)
    await query.answer()


@router.callback_query(lambda query: query.data and query.data.startswith("game:rps:"))
async def rps_callback(query: CallbackQuery, db: Database):
    if not query.message or not query.from_user:
        await query.answer()
        return
    parts = query.data.split(":")
    if len(parts) != 5:
        await query.answer("Раунд недействителен.", show_alert=True)
        return
    _, _, user_raw, nonce, player_choice = parts
    if not user_raw.isdigit() or int(user_raw) != query.from_user.id:
        await query.answer("Это не твой раунд.", show_alert=True)
        return
    key = (query.message.chat.id, query.from_user.id)
    if _rps_rounds.get(key) != nonce or player_choice not in _CHOICES:
        await query.answer("Этот раунд уже завершён. Начни новый через /games.", show_alert=True)
        return

    _rps_rounds.pop(key, None)
    bot_choice = random.choice(tuple(_CHOICES))
    if player_choice == bot_choice:
        outcome, points, won = "Ничья!", 1, False
    elif (player_choice, bot_choice) in {
        ("rock", "scissors"), ("scissors", "paper"), ("paper", "rock")
    }:
        outcome, points, won = "Ты победил!", 5, True
    else:
        outcome, points, won = "Я победил!", 0, False

    total, wins, played = await db.add_game_result(query.message.chat.id, query.from_user.id, points, won)
    await query.message.edit_reply_markup(reply_markup=None)
    await query.message.answer(
        f"Ты выбрал: <b>{_CHOICES[player_choice]}</b>\n"
        f"Я выбрал: <b>{_CHOICES[bot_choice]}</b>\n\n"
        f"{outcome} Игровые очки: <b>+{points}</b>.\n"
        f"Твой счёт: <b>{total}</b> | Побед: {wins}"
    )
    await query.answer()


@router.callback_query(lambda query: query.data and query.data.startswith("game:quiz:"))
async def quiz_callback(query: CallbackQuery, db: Database):
    if not query.message or not query.from_user:
        await query.answer()
        return
    parts = query.data.split(":")
    if len(parts) != 5:
        await query.answer("Вопрос недействителен.", show_alert=True)
        return
    _, _, user_raw, nonce, answer_raw = parts
    if not user_raw.isdigit() or int(user_raw) != query.from_user.id:
        await query.answer("Это не твой вопрос.", show_alert=True)
        return
    if not answer_raw.isdigit():
        await query.answer("Ответ недействителен.", show_alert=True)
        return
    key = (query.message.chat.id, query.from_user.id)
    active = _quiz_rounds.get(key)
    if not active or active[0] != nonce:
        await query.answer("Этот вопрос уже закрыт. Начни новый через /games.", show_alert=True)
        return

    _quiz_rounds.pop(key, None)
    correct = int(answer_raw) == active[1]
    points = 3 if correct else 0
    total, wins, played = await db.add_game_result(query.message.chat.id, query.from_user.id, points, correct)
    await query.message.edit_reply_markup(reply_markup=None)
    result = "✅ Правильно!" if correct else "❌ Неверно!"
    await query.message.answer(
        f"{result} Игровые очки: <b>+{points}</b>.\n"
        f"Твой счёт: <b>{total}</b> | Правильных ответов: {wins}"
    )
    await query.answer()


@router.callback_query(lambda query: query.data == "game:top")
async def game_top_callback(query: CallbackQuery, db: Database):
    if not query.message:
        await query.answer()
        return
    await _send_top_games(query.message, db)
    await query.answer()


async def _send_top_games(message: Message, db: Database):
    leaders = await db.top_games(message.chat.id)
    if not leaders:
        await message.answer("🏆 Рейтинг пока пуст. Сыграй в /games, чтобы набрать первые очки.")
        return
    lines = ["🏆 <b>Рейтинг игрового зала</b>", ""]
    for index, (user_id, points, wins, played) in enumerate(leaders, start=1):
        try:
            member = await message.bot.get_chat_member(message.chat.id, user_id)
            name = escape(member.user.full_name)
        except Exception:
            name = f"Участник {user_id}"
        lines.append(f"{index}. {name} — <b>{points}</b> очков · побед: {wins} · игр: {played}")
    await message.answer("\n".join(lines))


@router.message(Command("topgames"))
async def top_games_command(message: Message, db: Database):
    if not _group_only(message):
        await message.answer("Рейтинг доступен в группе.")
        return
    await _send_top_games(message, db)


# Cancel any active game round for the current user.
@router.message(Command("cancel"), lambda m: m.chat.type != ChatType.PRIVATE and m.from_user is not None
                and ((m.chat.id, m.from_user.id) in _guess_games
                     or (m.chat.id, m.from_user.id) in _rps_rounds
                     or (m.chat.id, m.from_user.id) in _quiz_rounds))
async def cancel_game(message: Message):
    if not message.from_user:
        return
    key = (message.chat.id, message.from_user.id)
    _guess_games.pop(key, None)
    _rps_rounds.pop(key, None)
    _quiz_rounds.pop(key, None)
    await message.answer("Текущая игра отменена.")


# Allow the active "guess the number" round to accept a plain numeric message.
@router.message(lambda m: m.chat.type != ChatType.PRIVATE and m.from_user is not None
                and (m.chat.id, m.from_user.id) in _guess_games
                and (m.text or "").strip().isdigit()
                and not (m.text or "").startswith("/"))
async def guess_plain_text(message: Message, db: Database):
    if not message.from_user:
        return
    key = (message.chat.id, message.from_user.id)
    game = _guess_games.get(key)
    if not game:
        return
    guess = int((message.text or "").strip())
    if not GUESS_MIN <= guess <= GUESS_MAX:
        await message.answer(f"Введи число от {GUESS_MIN} до {GUESS_MAX}.")
        return
    game["attempts"] -= 1
    target = game["number"]
    if guess == target:
        _guess_games.pop(key, None)
        points, wins, played = await db.add_game_result(message.chat.id, message.from_user.id, 10, True)
        await message.answer(f"🎉 Верно! Это было {target}. Начислено +10 игровых очков. Твой счёт: {points}.")
    elif game["attempts"] <= 0:
        _guess_games.pop(key, None)
        await db.add_game_result(message.chat.id, message.from_user.id, 0, False)
        await message.answer(f"Попытки закончились! Загаданное число: {target}.")
    else:
        hint = "больше" if guess < target else "меньше"
        await message.answer(f"Не угадал, моё число {hint}. Осталось попыток: {game['attempts']}.")
