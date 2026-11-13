import asyncio
from datetime import datetime, timedelta, timezone
from html import escape

from aiogram import Bot, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, ChatPermissions
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.db import Database
from handlers.ranks import get_rank, can_action
from handlers.moderation import bot_can_restrict, target_is_restrictable

router = Router()


async def _safe_edit(message: Message, text: str, reply_markup=None) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if "message is not modified" not in exc.message.lower():
            raise

async def _safe_answer(message: Message, text: str, **kwargs) -> None:
    """Retry a user-facing reply once when Telegram applies temporary flood control."""
    try:
        await message.answer(text, **kwargs)
    except TelegramRetryAfter as exc:
        await asyncio.sleep(max(1, exc.retry_after))
        await message.answer(text, **kwargs)

# Pending participant selection: (chat_id, admin_id)
pending_selection: set[tuple[int, int]] = set()


def main_menu():
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🛡 Модерация", callback_data="vortex:moderation")
    keyboard.button(text="👤 Выбрать участника", callback_data="vortex:select_member")
    keyboard.button(text="⚠️ Предупреждения", callback_data="vortex:warnings")
    keyboard.button(text="🚫 Антифлуд", callback_data="vortex:antiflood")
    keyboard.button(text="📊 Статистика", callback_data="vortex:stats")
    keyboard.button(text="👤 Профиль", callback_data="vortex:profile")
    keyboard.button(text="⭐ Репутация", callback_data="vortex:reputation")
    keyboard.button(text="💰 Экономика", callback_data="vortex:economy")
    keyboard.button(text="🛒 Предметы и рынок", callback_data="vortex:shop")
    keyboard.button(text="🎮 Игры", callback_data="vortex:games")
    keyboard.button(text="📜 Ежедневные задания", callback_data="quests:show")
    keyboard.button(text="👋 Приветствие", callback_data="vortex:welcome")
    keyboard.button(text="📖 Все команды", callback_data="vortex:commands")
    keyboard.adjust(2, 2, 2, 2, 2, 2, 1)
    return keyboard.as_markup()


def games_menu():
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🔢 Угадай число", callback_data="game:start:guess")
    keyboard.button(text="✊ Камень, ножницы, бумага", callback_data="game:start:rps")
    keyboard.button(text="🧠 Викторина", callback_data="game:start:quiz")
    keyboard.button(text="🏆 Рейтинг игр", callback_data="game:top")
    keyboard.button(text="⬅️ В главное меню", callback_data="vortex:home")
    keyboard.adjust(1)
    return keyboard.as_markup()


def shop_menu():
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🛍 Каталог магазина", callback_data="shopui:catalog")
    keyboard.button(text="🎒 Мой инвентарь", callback_data="shopui:inventory")
    keyboard.button(text="🏪 Рынок игроков", callback_data="shopui:market")
    keyboard.button(text="⬅️ В главное меню", callback_data="vortex:home")
    keyboard.adjust(1)
    return keyboard.as_markup()


def back_menu():
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="⬅️ В главное меню", callback_data="vortex:home")
    return keyboard.as_markup()

def private_shop_menu():
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🛍 Каталог и цены", callback_data="shopinfo:catalog")
    keyboard.button(text="✨ Эффекты предметов", callback_data="shopinfo:effects")
    keyboard.button(text="📦 Как получить и использовать", callback_data="shopinfo:howto")
    keyboard.button(text="⬅️ В главное меню", callback_data="shopinfo:home")
    keyboard.adjust(1)
    return keyboard.as_markup()


def economy_section_keyboard():
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="💰 Мой баланс", callback_data="eco:balance")
    keyboard.button(text="🎁 Ежедневная награда", callback_data="eco:daily")
    keyboard.button(text="💸 Перевести монеты", callback_data="eco:transfer")
    keyboard.button(text="💱 Обменять игровые очки", callback_data="eco:exchange")
    keyboard.button(text="🏆 Топ богачей", callback_data="eco:top")
    keyboard.button(text="⬅️ В главное меню", callback_data="vortex:home")
    keyboard.adjust(1)
    return keyboard.as_markup()


def profile_section_keyboard():
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="👤 Мой профиль", callback_data="profile:me")
    keyboard.button(text="⭐ Выдать репутацию", callback_data="profile:give")
    keyboard.button(text="🏆 Топ репутации", callback_data="profile:toprep")
    keyboard.button(text="📈 Топ активности", callback_data="profile:topactivity")
    keyboard.button(text="⬅️ В главное меню", callback_data="vortex:home")
    keyboard.adjust(1)
    return keyboard.as_markup()


def stats_section_keyboard():
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="📈 Топ активности", callback_data="profile:topactivity")
    keyboard.button(text="🏆 Топ репутации", callback_data="profile:toprep")
    keyboard.button(text="⬅️ В главное меню", callback_data="vortex:home")
    keyboard.adjust(1)
    return keyboard.as_markup()



def member_actions(chat_id: int, user_id: int):
    keyboard = InlineKeyboardBuilder()
    for label, action in [
        ("👁 Посмотреть предупреждения", "warnings"),
        ("⚠️ Выдать предупреждение", "warn"),
        ("🔇 Мут на 10 минут", "mute"),
        ("🔊 Снять мут", "unmute"),
        ("👢 Исключить", "kick"),
        ("⛔ Заблокировать", "ban"),
        ("🧹 Очистить предупреждения", "clearwarns"),
    ]:
        keyboard.button(text=label, callback_data=f"vortex:act:{action}:{chat_id}:{user_id}")
    keyboard.button(text="⬅️ В главное меню", callback_data="vortex:home")
    keyboard.adjust(1)
    return keyboard.as_markup()


MENU_TEXT = {
    "moderation": (
        "🛡 <b>Модерация</b>\n\n"
        "Нажми «Выбрать участника», чтобы открыть действия для конкретного пользователя. "
        "Также можно использовать команды ответом на его сообщение:\n"
        "/mute 10m — ограничить на 10 минут\n"
        "/unmute — снять ограничение\n"
        "/kick — удалить из группы\n"
        "/ban — заблокировать\n"
        "/unban ID — снять блокировку по Telegram ID\n"
        "/ranks — иерархия прав\n"
        "/myrank — мой ранг модерации\n"
        "/setrank 1 — назначить ранг ответом на сообщение (для ранга 5+) "
    ),
    "warnings": (
        "⚠️ <b>Предупреждения</b>\n\n"
        "Нажми «Выбрать участника» в главном меню, чтобы выдать или очистить предупреждения.\n"
        "/warn, /warnings, /clearwarns — также работают ответом на сообщение участника."
    ),
    "antiflood": (
        "🚫 <b>Защита от флуда</b>\n\n"
        "Антифлуд включён автоматически: бот отслеживает частые сообщения "
        "и удаляет сообщения сверх установленного лимита (6 сообщений за 8 секунд)."
    ),
    "stats": (
        "📊 <b>Статистика</b>\n\n"
        "Команда /stats показывает активность участников, количество сообщений, "
        "предупреждений и срабатываний антифлуда.\n"
        "/topactivity — рейтинг самых активных участников."
    ),
    "profile": (
        "👤 <b>Профили участников</b>\n\n"
        "/profile — посмотреть свой профиль\n"
        "Ответь командой /profile на сообщение, чтобы посмотреть профиль другого участника."
    ),
    "reputation": (
        "⭐ <b>Репутация</b>\n\n"
        "Ответь командой /rep на сообщение, чтобы выдать +1 репутации.\n"
        "/toprep — рейтинг участников. Повторно выдать репутацию одному человеку можно на следующий день."
    ),
    "economy": (
        "💰 <b>Экономика VORTEX</b>\n\n"
        "/balance — посмотреть баланс\n"
        "/daily — получить ежедневные 100 V-coins\n"
        "Ответь командой /pay 50 на сообщение участника, чтобы перевести ему 50 монет.\n"
        "/topmoney — рейтинг богачей группы\n"
        "/exchange 100 — обменять 100 игровых очков на 10 V-coins. Курс 10:1.\n\n"
        "Покупка, подарки и торговля предметами — в разделе «Предметы и рынок»."
    ),
    "games": (
        "🎮 <b>Игровой зал VORTEX</b>\n\n"
        "Играй прямо в группе, зарабатывай игровые очки и поднимайся в рейтинге.\n"
        "🔢 Угадай число — найди число от 1 до 63 за 5 попыток (+10 очков).\n"
        "✊ Камень, ножницы, бумага — сыграй против бота (до +5 очков).\n"
        "🧠 Викторина — два варианта ответа, шанс случайного угадывания 50% (+3 очка).\n\n"
        "Игровые очки отдельны от V-coins. Команда /topgames покажет рейтинг.\n"
        "Обмен: /exchange 100 — 100 игровых очков = 10 V-coins."
    ),
    "welcome": (
        "👋 <b>Приветствие</b>\n\n"
        "Бот автоматически приветствует новых участников, когда они вступают в группу."
    ),
    "commands": (
        "📖 <b>Список команд</b>\n\n"
        "<b>Модерация:</b>\n"
        "/warn — предупреждение (ответом)\n"
        "/warnings — число предупреждений (ответом)\n"
        "/clearwarns — очистить предупреждения (ответом)\n"
        "/mute 10m, /unmute, /kick, /ban — действия (ответом)\n"
        "/unban ID — разблокировать по Telegram ID\n"
        "/ranks, /myrank, /setrank — система рангов модерации\n"
        "/stats — статистика группы\n"
        "/audit — журнал действий модерации\n\n"
        "<b>Профиль и репутация:</b>\n"
        "/profile, /rep (ответом), /toprep, /topactivity\n"
        "/achievements — мои достижения\n\n"
        "<b>Экономика:</b>\n"
        "/balance, /daily, /pay 50 (ответом), /topmoney\n"
        "/exchange 100 — обмен игровых очков на V-coins\n"
        "/quests — ежедневные задания\n"
        "/claimquests — забрать награды за выполненные задания\n\n"
        "<b>Игры:</b>\n"
        "/games, /guessgame, /guess 50, /topgames\n\n"
        "<b>Предметы и рынок:</b>\n"
        "/shop — каталог\n"
        "/buyitem rose 2 — купить предмет\n"
        "/inventory — инвентарь\n"
        "/useitem lucky_charm — использовать расходник\n"
        "/giftitem rose 1 — подарить (ответом на сообщение)\n"
        "/sellitem rose 1 150 — выставить на рынок\n"
        "/market — объявления игроков\n"
        "/buylisting 12 — купить лот\n"
        "/cancel_listing 12 — снять своё объявление и вернуть предметы"
    ),
}


async def user_is_admin(db: Database, bot: Bot, chat_id: int, user_id: int, owner_ids: frozenset[int]) -> bool:
    return await get_rank(db, bot, chat_id, user_id, owner_ids) >= 1


@router.message(Command("start"))
async def start_command(message: Message):
    await _safe_answer(message,
        "🌪 <b>VORTEX BOT</b>\n"
        "Твой помощник по управлению Telegram-группой.\n\n"
        "Выбери нужный раздел в меню:",
        reply_markup=main_menu(),
    )


@router.message(Command("help"))
async def help_command(message: Message):
    await _safe_answer(message,
        "📖 <b>Справка VORTEX BOT</b>\n\n"
        "Выбери раздел в меню ниже. Действия модерации доступны по рангу VORTEX.",
        reply_markup=main_menu(),
    )


@router.message(Command("cancel"), lambda m: m.chat.type != "private" and m.from_user is not None)
async def cancel_member_selection(message: Message):
    if not message.from_user:
        return
    # Clear every pending group flow so an older prompt cannot consume the next message.
    from handlers import economy, games, profile, shop
    key = (message.chat.id, message.from_user.id)
    pending_selection.discard(key)
    profile._profile_pending_rep.discard(key)
    economy._economy_pending.pop(key, None)
    games._guess_games.pop(key, None)
    games._rps_rounds.pop(key, None)
    games._quiz_rounds.pop(key, None)
    shop._pending_shop_action.pop(key, None)
    await message.answer("Все ожидающие операции и текущая игра отменены.")


@router.message(lambda message: message.chat.type != "private" and message.reply_to_message is not None and message.from_user is not None and (message.chat.id, message.from_user.id) in pending_selection)
async def receive_selected_member(message: Message, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not message.from_user:
        return
    key = (message.chat.id, message.from_user.id)
    if key not in pending_selection:
        return
    pending_selection.discard(key)

    if not await user_is_admin(db, bot, message.chat.id, message.from_user.id, owner_ids):
        await message.answer("Выбирать участников через это меню могут только администраторы.")
        return
    target = message.reply_to_message.from_user
    if not target:
        await message.answer("Не удалось определить автора сообщения. Ответь на обычное сообщение участника.")
        return
    if target.is_bot:
        await message.answer("Нельзя применить действия к боту.")
        return
    if target.id == message.from_user.id:
        await message.answer("Нельзя выбрать самого себя.")
        return

    await message.answer(
        f"👤 Выбран участник: <b>{escape(target.full_name)}</b>\n"
        f"ID: <code>{target.id}</code>\n\n"
        "Выбери действие:",
        reply_markup=member_actions(message.chat.id, target.id),
    )


@router.callback_query(lambda query: query.data == "vortex:select_member")
async def select_member_callback(query: CallbackQuery, bot: Bot, db: Database, owner_ids: frozenset[int]):
    if not query.message or not query.from_user:
        await query.answer()
        return
    if query.message.chat.type == "private":
        await query.answer("Открой меню в группе.", show_alert=True)
        return
    if not await user_is_admin(db, bot, query.message.chat.id, query.from_user.id, owner_ids):
        await query.answer("Только для администраторов группы.", show_alert=True)
        return
    pending_selection.add((query.message.chat.id, query.from_user.id))
    await query.message.answer(
        "👤 <b>Выбор участника</b>\n\n"
        "Найди сообщение нужного участника в чате и ответь на него любым текстом. "
        "После этого появится меню действий."
    )
    await query.answer()


@router.callback_query(lambda query: query.data and query.data.startswith("vortex:act:"))
async def member_action_callback(
    query: CallbackQuery,
    bot: Bot,
    db: Database,
    owner_ids: frozenset[int],
):
    if not query.message or not query.from_user:
        await query.answer()
        return
    parts = query.data.split(":")
    if len(parts) != 5:
        await query.answer("Некорректное действие.", show_alert=True)
        return
    _, _, action, chat_id_raw, user_id_raw = parts
    try:
        chat_id, user_id = int(chat_id_raw), int(user_id_raw)
    except ValueError:
        await query.answer("Некорректный участник.", show_alert=True)
        return
    if query.message.chat.id != chat_id:
        await query.answer("Это меню относится к другой группе.", show_alert=True)
        return
    if not await can_action(db, bot, chat_id, query.from_user.id, action, owner_ids):
        await query.answer("Недостаточно прав для этого действия.", show_alert=True)
        return
    if user_id == query.from_user.id:
        await query.answer("Нельзя применить действие к самому себе.", show_alert=True)
        return
    try:
        target_member = await bot.get_chat_member(chat_id, user_id)
        target = target_member.user
        if (
            target_member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)
            and action not in ("warn", "warnings", "clearwarns")
        ):
            await query.answer(
                "Администратора можно предупредить, но ограничить или исключить его через бота нельзя.",
                show_alert=True,
            )
            return

        if action in ("mute", "unmute", "kick", "ban"):
            if not await bot_can_restrict(query.message, bot):
                await query.answer("У бота недостаточно прав. Подробности отправлены в группу.", show_alert=True)
                return
            if not await target_is_restrictable(query.message, bot, target):
                await query.answer("Нельзя применить это действие к данному участнику.", show_alert=True)
                return

        if action == "warnings":
            count = await db.warning_count(chat_id, user_id)
            result = f"👁 У {escape(target.full_name)} предупреждений: {count}."
        elif action == "warn":
            count = await db.add_warning(chat_id, user_id, query.from_user.id, "Выдано через меню")
            await db.log_event(chat_id, "warn")
            result = f"⚠️ {escape(target.full_name)} получил предупреждение. Всего: {count}."
        elif action == "clearwarns":
            await db.clear_warnings(chat_id, user_id)
            result = f"🧹 Предупреждения пользователя {escape(target.full_name)} очищены."
        elif action == "mute":
            await bot.restrict_chat_member(
                chat_id, user_id,
                permissions=ChatPermissions(
                can_send_messages=False,
                can_send_audios=False,
                can_send_documents=False,
                can_send_photos=False,
                can_send_videos=False,
                can_send_video_notes=False,
                can_send_voice_notes=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
                can_manage_topics=False,
            ),
                until_date=datetime.now(timezone.utc) + timedelta(minutes=10),
            )
            result = f"🔇 {escape(target.full_name)} ограничен на 10 минут."
        elif action == "unmute":
            chat_info = await bot.get_chat(chat_id)
            await bot.restrict_chat_member(
                chat_id, user_id,
                permissions=chat_info.permissions or ChatPermissions(
                    can_send_messages=True, can_send_audios=True, can_send_documents=True,
                    can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
                    can_send_voice_notes=True, can_send_polls=True,
                    can_send_other_messages=True, can_add_web_page_previews=True,
                    can_manage_topics=False,
                ),
            )
            result = f"🔊 Ограничения сняты: {escape(target.full_name)}."
        elif action == "kick":
            await bot.ban_chat_member(chat_id, user_id)
            await bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
            result = f"👢 {escape(target.full_name)} исключён из группы."
        elif action == "ban":
            await bot.ban_chat_member(chat_id, user_id)
            result = f"⛔ {escape(target.full_name)} заблокирован."
        else:
            await query.answer("Неизвестное действие.", show_alert=True)
            return
        await db.log_moderation_action(chat_id, query.from_user.id, user_id, action, "через меню")
        await query.message.answer(result)
        await query.answer("Готово.")
    except TelegramAPIError as exc:
        await query.answer(f"Не удалось выполнить действие: {exc.message}", show_alert=True)


@router.callback_query(lambda query: query.data and query.data.startswith("shopinfo:"))
async def private_shop_info_callback(query: CallbackQuery):
    if not query.message or query.message.chat.type != "private":
        await query.answer("Открой этот раздел в личном чате с ботом.", show_alert=True)
        return
    section = query.data.split(":", 1)[1]
    if section == "home":
        await _safe_edit(query.message, "🌪 <b>VORTEX BOT</b>\nТвой помощник по управлению Telegram-группой.", reply_markup=main_menu())
    elif section in ("catalog", "effects"):
        from handlers.shop import ITEMS
        heading = "🛍 <b>Каталог предметов VORTEX</b>" if section == "catalog" else "✨ <b>Эффекты предметов</b>"
        lines = [heading, ""]
        for code, item in ITEMS.items():
            lines.append(f"{item['name']} — <b>{item['price']:,} V-coins</b>")
            lines.append(f"<code>{code}</code> · {item['description']}")
            lines.append("")
        if section == "effects":
            lines.append("Важно: сейчас предметы дают только указанные игровые очки. Дополнительные бонусы не активированы.")
        else:
            lines.append("Цены указаны за 1 предмет. Покупка доступна в группе: /buyitem rose 1.")
        await _safe_edit(query.message, "\n".join(lines), reply_markup=private_shop_menu())
    elif section == "howto":
        await _safe_edit(query.message,
            "📦 <b>Как пользоваться предметами</b>\n\n"
            "1. Получи V-coins за активность, игры и задания.\n"
            "2. В группе купи предмет: <code>/buyitem rose 2</code>.\n"
            "3. Проверь вещи: <code>/inventory</code>.\n"
            "4. Используй предмет: <code>/useitem rose</code> — он спишется, а игровые очки начислятся.\n"
            "5. Подари предмет ответом на сообщение: <code>/giftitem rose 1</code>.\n"
            "6. Выставь на рынок: <code>/sellitem rose 1 150</code>.\n"
            "7. Просмотри рынок: <code>/market</code>; купить лот: <code>/buylisting 12</code>.\n\n"
            "Инвентарь и рынок ведутся отдельно для каждой группы. В личном чате доступна справка.",
            reply_markup=private_shop_menu())
    else:
        await query.answer("Раздел не найден.", show_alert=True)
        return
    await query.answer()


@router.callback_query(lambda query: query.data and query.data.startswith("vortex:"))
async def menu_callback(query: CallbackQuery, db: Database):
    section = query.data.split(":", 1)[1]
    if not query.message:
        await query.answer()
        return
    if query.message.chat.type == "private":
        if section == "home":
            await _safe_edit(query.message,
                "🌪 <b>VORTEX BOT</b>\\nТвой помощник по управлению Telegram-группой.\\n\\nВыбери нужный раздел:",
                reply_markup=main_menu())
        elif section == "shop":
            await _safe_edit(query.message,
                "🎒 <b>Предметы VORTEX</b>\n\n"
                "Здесь можно изучить каталог, цены, эффекты и правила использования. "
                "Покупка, инвентарь и торговля привязаны к выбранной группе.",
                reply_markup=private_shop_menu())
        elif section in MENU_TEXT:
            descriptions = {
                "moderation": "🛡 <b>Модерация</b>\n\nСправка по командам и системе прав. Применять санкции к участникам можно только внутри группы, где бот имеет права администратора.",
                "warnings": "⚠️ <b>Предупреждения</b>\n\nПросмотр и изменение предупреждений относятся к конкретной группе. В личке доступна справка, а сами действия выполняются в группе.",
                "antiflood": MENU_TEXT["antiflood"],
                "stats": "📊 <b>Статистика группы</b>\n\nСтатистика считается отдельно для каждой группы. Открой этот раздел в нужной группе, чтобы увидеть реальные показатели.",
                "profile": "👤 <b>Профиль</b>\n\nПрофили и достижения хранятся отдельно в каждой группе. Открой раздел в группе, чтобы увидеть профиль и достижения именно там.",
                "reputation": "⭐ <b>Репутация</b>\n\nРепутация и рейтинги относятся к участникам конкретной группы. Выдавать репутацию можно ответом на сообщение в группе.",
                "economy": "💰 <b>Экономика VORTEX</b>\n\nБаланс, ежедневные награды, переводы и обмен ведутся отдельно для каждой группы. Используй этот раздел в нужной группе.",
                "games": MENU_TEXT["games"],
                "welcome": MENU_TEXT["welcome"],
                "commands": MENU_TEXT["commands"],
            }
            await _safe_edit(query.message, descriptions.get(section, MENU_TEXT[section]) +
                "\n\n<i>Это информационная страница личного чата. Групповые данные и действия доступны в соответствующей группе.</i>",
                reply_markup=back_menu())
        elif section == "select_member":
            await _safe_edit(query.message,
                "👤 <b>Выбор участника</b>\n\nЭта функция требует контекста группы: в личном чате нельзя определить, из какой группы выбрать участника. Открой меню в нужной группе.",
                reply_markup=back_menu())
        else:
            await _safe_edit(query.message,
                "Этот раздел требует контекста конкретной группы. Открой его в группе, где добавлен VORTEX BOT.",
                reply_markup=back_menu())
        await query.answer()
        return
    if section == "home":
        text = (
            "🌪 <b>VORTEX BOT</b>\n"
            "Твой помощник по управлению Telegram-группой.\n\n"
            "Выбери нужный раздел в меню:"
        )
        await _safe_edit(query.message, text, reply_markup=main_menu())
    elif section == "games":
        await _safe_edit(query.message, MENU_TEXT[section], reply_markup=games_menu())
    elif section == "shop":
        await _safe_edit(query.message, 
            "🛒 <b>Предметы и рынок VORTEX</b>\n\n"
            "Покупай предметы за V-coins, храни их в инвентаре, используй расходники, "
            "дарить предметы другим участникам или выставляй их на рынок.",
            reply_markup=shop_menu(),
        )
    elif section == "shop_catalog":
        await _safe_edit(query.message, 
            "🛍 <b>Каталог магазина</b>\n\n"
            "🌹 Роза — 100 V-coins\n"
            "🍫 Шоколад — 250 V-coins\n"
            "🏆 Кубок — 1 000 V-coins\n"
            "👑 Корона — 2 500 V-coins\n"
            "🍀 Талисман удачи — 400 V-coins (+5 игровых очков при использовании)\n\n"
            "Купить: <code>/buyitem rose 2</code>\n"
            "После покупки предмет появится в твоём инвентаре.",
            reply_markup=shop_menu(),
        )
    elif section == "shop_inventory":
        await _safe_edit(query.message, 
            "🎒 <b>Инвентарь</b>\n\n"
            "Команда /inventory покажет твои предметы.\n\n"
            "Использовать расходник: /useitem lucky_charm\n"
            "Подарить предмет: ответь на сообщение участника командой /giftitem rose 1\n"
            "Выставить на рынок: /sellitem rose 1 150",
            reply_markup=shop_menu(),
        )
    elif section == "shop_market":
        await _safe_edit(query.message, 
            "🏪 <b>Рынок игроков</b>\n\n"
            "/market — посмотреть объявления\n"
            "/sellitem rose 1 150 — выставить предмет (цена за штуку)\n"
            "/buylisting 12 — купить лот целиком\n\n"
            "С продавца удерживается комиссия 5%. Предметы резервируются до продажи.",
            reply_markup=shop_menu(),
        )
    elif section == "economy":
        await _safe_edit(query.message, 
            "💰 <b>Экономика VORTEX</b>\n\n"
            "Управляй монетами кнопками ниже. Для перевода выбери кнопку и ответь суммой на сообщение получателя. "
            "Для обмена очков просто введи количество после нажатия кнопки.",
            reply_markup=economy_section_keyboard(),
        )
    elif section in ("profile", "reputation"):
        await _safe_edit(query.message, 
            "👤 <b>Профиль и репутация</b>\n\n"
            "Просматривай профиль, рейтинги и выдавай репутацию через кнопки.",
            reply_markup=profile_section_keyboard(),
        )
    elif section == "stats":
        data = await db.chat_stats(query.message.chat.id)
        await _safe_edit(query.message, 
            "📊 <b>Статистика группы</b>\n\n"
            f"Участников в базе: <b>{data['users']}</b>\n"
            f"Сообщений: <b>{data['messages']}</b>\n"
            f"Предупреждений: <b>{data['warnings']}</b>\n"
            f"Срабатываний антифлуда: <b>{data['antiflood']}</b>",
            reply_markup=stats_section_keyboard(),
        )
    elif section in MENU_TEXT:
        await _safe_edit(query.message, MENU_TEXT[section], reply_markup=back_menu())
    await query.answer()
