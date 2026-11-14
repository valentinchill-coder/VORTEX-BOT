import re

from aiogram import Router
from aiogram.enums import ChatType
from aiogram.types import Message

from database.db import Database
from handlers import economy, games, moderation, profile, shop, start, private_panel, ranks, quests

router = Router()

_NUMBER_WORDS = {
    "один": 1, "одну": 1, "одна": 1, "однажды": 1,
    "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5,
    "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10,
}
_ITEM_ALIASES = {
    "rose": ("rose", r"роз(?:а|у|ы|е|ой)"),
    "choco": ("choco", r"шоколад(?:ку|а|ку)?"),
    "trophy": ("trophy", r"куб(?:ок|ка|ок|ки)"),
    "crown": ("crown", r"корон(?:а|у|ы|е)"),
    "lucky_charm": ("lucky_charm", r"(?:талисман(?:а)?|оберег(?:а)?)"),
}


def _number(value: str | None, default: int = 1) -> int:
    if not value:
        return default
    value = value.lower()
    return int(value) if value.isdigit() else _NUMBER_WORDS.get(value, default)


def parse_intent(text: str) -> str | None:
    """Translate common Russian requests into the bot's existing command syntax."""
    raw = (text or "").strip()
    if not raw or raw.startswith("/"):
        return None
    value = raw.lower().replace("ё", "е")
    value = re.sub(r"[!?.,]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()

    # Moderation ranks: natural-language aliases.
    if re.search(r"\b(мой ранг|какой у меня ранг|покажи мой ранг)\b", value):
        return "__myrank__"
    if re.search(r"\b(покажи ранги|список рангов|иерархия рангов|какие ранги есть|какие есть ранги|какие у нас ранги|перечисли ранги)\b", value):
        return "__ranks__"
    if re.search(r"\b(снять ранг|сними ранг|обнули ранг|убери ранг|сбрось ранг)\b", value):
        return "__rank_remove__"
    if re.search(r"\b(повысить|повышение|подними ранг)\b", value):
        return "__rank_up__"
    if re.search(r"\b(понизить|понижение|опусти ранг)\b", value):
        return "__rank_down__"
    rank_match = re.search(r"\b(?:выдай|выдать|назначь|назначить|установи)\s+(?:ему\s+|ей\s+)?(?:ранг\s*)?([0-7])\b", value)
    if rank_match:
        return f"__rank_set_{rank_match.group(1)}__"
    if re.search(r"\b(выдать ранг|назначить ранг|поставить ранг)\b", value):
        return "__rank_usage__"

    if re.search(r"\b(мои достижения|покажи достижения|список достижений)\b", value):
        return "/achievements"

    if re.search(r"\b(мои задания|задания на сегодня|покажи квесты|ежедневные задания)\b", value):
        return "/quests"
    if re.search(r"\b(забрать награды за задания|получи награды за квесты|забери награды)\b", value):
        return "/claimquests"

    # Read-only information and navigation.
    if re.search(r"\b(баланс|сколько у меня (?:монет|денег)|покажи (?:мои )?монеты)\b", value):
        return "/balance"
    if re.search(r"\b(ежедневн\w* наград\w*|дейлик|забрать награду|получи(ть)? бонус)\b", value):
        return "/daily"
    if re.search(r"\b(топ богач\w*|рейтинг богат\w*|кто самый богат\w*)\b", value):
        return "/topmoney"
    if re.search(r"\b(мой профиль|покажи профиль|посмотреть профиль)\b", value):
        return "/profile"
    if re.search(r"\b(топ репутац\w*|рейтинг репутац\w*)\b", value):
        return "/toprep"
    if re.search(r"\b(топ активност\w*|самые активные|рейтинг активност\w*)\b", value):
        return "/topactivity"
    if re.search(r"\b(статистик\w* групп\w*|покажи статистику|статистика чата)\b", value):
        return "/stats"
    if re.search(r"\b(магазин|каталог|что продается|что можно купить)\b", value):
        return "/shop"
    if re.search(r"\b(мой инвентарь|покажи инвентарь|мои предметы)\b", value):
        return "/inventory"
    if re.search(r"\b(рынок|покажи рынок|объявления игроков)\b", value):
        return "/market"
    if re.search(r"\b(топ игр|рейтинг игр|лидеры игр)\b", value):
        return "/topgames"
    # Games.
    if re.search(r"\b(угадай число|игра угадай|загадай число)\b", value):
        return "__game_guess__"
    if re.search(r"\b(камень ножницы бумага|кнб|сыграть в камень)\b", value):
        return "__game_rps__"
    if re.search(r"\b(викторин\w*|квиз|вопрос на знание)\b", value):
        return "__game_quiz__"

    if re.search(r"\b(игры|игровой зал|начни игру|хочу поиграть)\b", value):
        return "/games"

    # Economy.
    match = re.search(r"\b(?:обменяй|обменять|конвертируй)\s+(\d+)\s*(?:игровых?\s*)?(?:очк\w*)", value)
    if match:
        return f"/exchange {match.group(1)}"
    match = re.search(r"\b(?:переведи|отправь|скинь)\s+(\d+)\s*(?:v-?coins?|монет\w*|коин\w*)", value)
    if match:
        return f"/pay {match.group(1)}"
    match = re.search(r"\b(?:выдай|дай)\s+(?:репутац\w*|звезд\w*)", value)
    if match:
        return "/rep"

    # Shop purchases and item actions.
    for code, (item_code, pattern) in _ITEM_ALIASES.items():
        buy = re.search(rf"\b(?:купи|купить|приобрети)\s+(?:(\d+|одну|один|одна|две|два|три|четыре|пять)\s+)?{pattern}\b", value)
        if buy:
            return f"/buyitem {item_code} {_number(buy.group(1))}"
        use = re.search(rf"\b(?:используй|примени)\s+{pattern}\b", value)
        if use:
            return f"/useitem {item_code}"
        gift = re.search(rf"\b(?:подари|подарить)\s+(?:(\d+|одну|один|одна|две|два|три|четыре|пять)\s+)?{pattern}\b", value)
        if gift:
            return f"/giftitem {item_code} {_number(gift.group(1))}"
        sell = re.search(rf"\b(?:продай|выстави)\s+(?:(\d+|одну|один|одна|две|два|три|четыре|пять)\s+)?{pattern}\s+(?:за\s+)?(\d+)\b", value)
        if sell:
            return f"/sellitem {item_code} {_number(sell.group(1))} {sell.group(2)}"

    match = re.search(r"\b(?:купи|покупай)\s+(?:лот|объявление)\s*(?:номер\s*)?(\d+)\b", value)
    if match:
        return f"/buylisting {match.group(1)}"
    match = re.search(r"\b(?:сними|отмени|верни)\s+(?:свой\s+)?(?:лот|объявление)\s*(?:номер\s*)?(\d+)\b", value)
    if match:
        return f"/cancel_listing {match.group(1)}"

    if re.search(r"\b(журнал модерации|история модерации|последние действия модераторов)\b", value):
        return "/audit"

    # Moderation. These actions still go through the existing admin permission checks.
    if re.search(r"\b(сними|снять|убери|убрать|отмени|отменить)\s+(?:мне\s+)?(?:варн\w*|предупреждени\w*)\b", value):
        return "/clearwarns"
    if re.search(r"\b(варн|warn|выдай варн|выдай предупреждение|предупреди участника|предупреди|предупреждение пользователю)\b", value):
        reason = re.sub(r"^.*?(?:варн|warn|выдай предупреждение|предупреди участника|предупреди|предупреждение пользователю)\s*", "", raw, flags=re.I).strip()
        return "/warn" + (f" {reason}" if reason else "")
    if re.search(r"\b(сколько предупреждений|покажи предупреждения)\b", value):
        return "/warnings"
    if re.search(r"\b(очисти предупреждения|сбрось предупреждения)\b", value):
        return "/clearwarns"
    if re.search(r"\b(сними|снять|убери|убрать|отмени|отменить)\s+(?:мне\s+)?мут\w*\b|\b(размути|размут|анмут|верни возможность писать)\b", value):
        username = re.search(r"@([a-z0-9_]{5,32})", raw, re.I)
        return f"/unmute @{username.group(1)}" if username else "/unmute"
    if re.search(r"\b(замути|замутить|замуть|мут|mute|ограничь писать)\b", value):
        # Extract one or more duration parts, e.g. "1 час 30 минут".
        duration_parts = re.findall(
            r"(\d+)\s*(д(?:ень|ня|ней|н\.)?|ч(?:ас|аса|асов|\.)?|м(?:инут\w*|ин\.)?)",
            value,
        )
        if not duration_parts:
            return "/mute 10m"
        normalized = []
        for amount, unit_word in duration_parts:
            unit = "d" if unit_word.startswith("д") else ("h" if unit_word.startswith("ч") else "m")
            normalized.append(f"{amount}{unit}")
        return "/mute " + "".join(normalized)
    if re.search(r"\b(разбань|разбанить|сними бан|unban)\b", value):
        match = re.search(r"@([a-z0-9_]{5,32})", raw, re.I)
        return f"/unban @{match.group(1)}" if match else "__need_unban_username__"
    if re.search(r"\b(забань|забанить|бан|бань|заблокируй участника|ban)\b", value):
        return "/ban"
    if re.search(r"\b(кикни|кикнуть|кик|исключи участника|удали участника из группы|kick)\b", value):
        return "/kick"

    if re.fullmatch(r"помощь|что ты умеешь|как тобой пользоваться|список возможностей", value):
        return "__help__"
    return None


async def _dispatch(message: Message, command_text: str, db: Database, bot, owner_ids):
    synthetic = message.model_copy(update={"text": command_text})
    command = command_text.split(maxsplit=1)[0]
    handlers = {
        "/balance": lambda: economy.balance_command(synthetic, db),
        "/daily": lambda: economy.daily_command(synthetic, db),
        "/pay": lambda: economy.pay_command(synthetic, db),
        "/topmoney": lambda: economy.top_money_command(synthetic, db),
        "/exchange": lambda: economy.exchange_command(synthetic, db),
        "/profile": lambda: profile.profile_command(synthetic, db, owner_ids),
        "/achievements": lambda: profile.achievements_command(synthetic, db),
        "/quests": lambda: quests.quests_command(synthetic, db),
        "/claimquests": lambda: quests.claim_quests_command(synthetic, db),
        "/rep": lambda: profile.reputation_command(synthetic, db),
        "/toprep": lambda: profile.top_reputation_command(synthetic, db),
        "/topactivity": lambda: profile.top_activity_command(synthetic, db),
        "/shop": lambda: shop.shop_command(synthetic),
        "/buyitem": lambda: shop.buy_item_command(synthetic, db),
        "/inventory": lambda: shop.inventory_command(synthetic, db),
        "/giftitem": lambda: shop.gift_item_command(synthetic, db),
        "/useitem": lambda: shop.use_item_command(synthetic, db),
        "/sellitem": lambda: shop.sell_item_command(synthetic, db),
        "/market": lambda: shop.market_command(synthetic, db),
        "/buylisting": lambda: shop.buy_listing_command(synthetic, db),
        "/cancel_listing": lambda: shop.cancel_listing_command(synthetic, db),
        "/warn": lambda: moderation.warn(synthetic, bot, db, owner_ids),
        "/warnings": lambda: moderation.warnings(synthetic, bot, db, owner_ids),
        "/clearwarns": lambda: moderation.clearwarns(synthetic, bot, db, owner_ids),
        "/mute": lambda: moderation.mute(synthetic, bot, db, owner_ids),
        "/unmute": lambda: moderation.unmute(synthetic, bot, db, owner_ids),
        "/kick": lambda: moderation.kick(synthetic, bot, db, owner_ids),
        "/ban": lambda: moderation.ban(synthetic, bot, db, owner_ids),
        "/unban": lambda: moderation.unban(synthetic, bot, db, owner_ids),
        "/audit": lambda: moderation.audit_command(synthetic, bot, db, owner_ids),
    }
    handler = handlers.get(command)
    if handler:
        await handler()
        return True
    if command == "/games":
        await games.games_command(synthetic)
        return True
    if command == "/guessgame":
        await games.guess_game_command(synthetic)
        return True
    if command == "/topgames":
        await games.top_games_command(synthetic, db)
        return True
    return False


@router.message(lambda m: m.text is not None and not m.text.startswith("/"))
async def natural_language_request(message: Message, db: Database, bot, owner_ids: frozenset[int]):
    if not message.from_user or message.from_user.is_bot:
        return
    intent = parse_intent(message.text or "")
    if intent is None:
        return
    if message.chat.type == ChatType.PRIVATE:
        if intent == "/profile":
            await private_panel.private_profile_command(message, db)
        else:
            await message.answer("В личном чате можно просматривать только свой профиль. Игры, экономика и управление доступны в группах; административные действия — только администраторам.")
        return
    if intent == "__help__":
        await message.answer(
            "🌪 <b>Я понимаю обычные запросы.</b> Например:\n"
            "• Покажи мой баланс\n• Забери ежедневную награду\n"
            "• Открой магазин / покажи инвентарь\n• Начни игру / викторину\n"
            "• Обменяй 100 игровых очков\n• Переведи 50 монет (ответом на сообщение)\n"
            "• Выдай предупреждение / замути на 10 минут (ответом на сообщение)\n"
            "• Купи две розы\n"
            "• Покажи ежедневные задания / забери награды за задания\n"
            "• Покажи мои достижения\n\n"
            "Для действий с другим участником ответь своим сообщением на его сообщение. "
            "Команды тоже продолжают работать."
        )
        return
    if intent in ("__myrank__", "__ranks__", "__rank_usage__", "__rank_remove__", "__rank_up__", "__rank_down__") or intent.startswith("__rank_set_"):
        await ranks.handle_natural_rank(message, db, bot, owner_ids, intent)
        return
    if intent == "__need_unban_username__":
        await message.answer("Напиши username в запросе: «Разбань @username».")
        return
    if intent.startswith("__game_"):
        if message.chat.type == ChatType.PRIVATE:
            await message.answer("Игры доступны в группе.")
            return
        action = intent.removeprefix("__game_")
        start_fn = {"guess": games._start_guess, "rps": games._start_rps, "quiz": games._start_quiz}[action]
        await start_fn(message.chat.id, message.from_user.id, message.answer)
        return
    if intent == "/stats":
        if message.chat.type == ChatType.PRIVATE:
            await message.answer("Статистика доступна в группе.")
            return
        stats = await db.chat_stats(message.chat.id)
        await message.answer(
            "📊 <b>Статистика группы</b>\n\n"
            f"Участников: <b>{stats['users']}</b>\n"
            f"Сообщений: <b>{stats['messages']}</b>\n"
            f"Предупреждений: <b>{stats['warnings']}</b>\n"
            f"Срабатываний антифлуда: <b>{stats['antiflood']}</b>"
        )
        return
    await _dispatch(message, intent, db, bot, owner_ids)
