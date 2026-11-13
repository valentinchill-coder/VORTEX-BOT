import asyncio
import logging
import os

import aiosqlite

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatMemberStatus, ParseMode
from aiogram.types import (
    ChatMemberUpdated,
    BotCommand,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllChatAdministrators,
)
from aiogram.filters import ChatMemberUpdatedFilter, JOIN_TRANSITION
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from config import load_settings
from database.db import Database
from handlers import start, moderation, admin, profile, economy, games, shop, natural, private_panel
from middlewares.antiflood import AntiFloodMiddleware
from handlers.shop import initialize_shop


WEBHOOK_PATH = "/telegram/webhook"


async def notify_audit_ready(bot: Bot, db: Database, owner_ids: frozenset[int]) -> None:
    """Send the requested one-time readiness notice to configured bot owners."""
    if os.getenv("AUDIT_READY_NOTIFY", "").strip() != "1":
        return
    recipients = set(owner_ids)
    if not recipients:
        # If OWNER_IDS was never configured, notify the creator of each known group.
        async with aiosqlite.connect(db.path) as conn:
            cursor = await conn.execute("SELECT DISTINCT chat_id FROM users")
            chat_ids = [int(row[0]) for row in await cursor.fetchall()]
        for chat_id in chat_ids:
            try:
                admins = await bot.get_chat_administrators(chat_id)
                creator = next(
                    (admin.user.id for admin in admins if admin.status == ChatMemberStatus.CREATOR),
                    None,
                )
                if creator:
                    recipients.add(creator)
            except Exception:
                logging.exception("Could not identify the creator of a known group for readiness notification")
    if not recipients:
        logging.error("AUDIT_READY_NOTIFY is enabled but no owner or known group creator could be identified")
        return

    async with aiosqlite.connect(db.path) as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        cursor = await conn.execute("SELECT value FROM bot_meta WHERE key='audit_ready_notice_v1'")
        row = await cursor.fetchone()
        if row and row[0] == "sent":
            return

    delivered = 0
    failed = 0
    for owner_id in recipients:
        try:
            await bot.send_message(owner_id, "Все работает и готово к использованию")
            delivered += 1
        except Exception:
            failed += 1
            logging.exception("Failed to send audit readiness notice to a configured owner")

    if delivered and not failed:
        async with aiosqlite.connect(db.path) as conn:
            await conn.execute(
                "INSERT INTO bot_meta(key,value) VALUES('audit_ready_notice_v1','sent') "
                "ON CONFLICT(key) DO UPDATE SET value='sent'"
            )
            await conn.commit()
        logging.info("Audit readiness notice delivered to configured bot owners")
    else:
        logging.error("Audit readiness notice incomplete: delivered=%s failed=%s", delivered, failed)


async def health_check(request: web.Request) -> web.Response:
    return web.Response(text="VORTEX BOT is running", content_type="text/plain")


async def welcome_new_members(event: ChatMemberUpdated, bot: Bot):
    if event.new_chat_member.status == "member":
        user = event.new_chat_member.user
        try:
            await bot.send_message(
                event.chat.id,
                f"Добро пожаловать, {user.mention_html()}! 🌪",
            )
        except Exception:
            logging.exception("Failed to send welcome message")


def create_dispatcher(db: Database, owner_ids: frozenset[int]) -> Dispatcher:
    dp = Dispatcher()
    dp["db"] = db
    dp["owner_ids"] = owner_ids
    dp.message.middleware(AntiFloodMiddleware(limit=6, window=8.0))

    # Private admin panel must precede the generic /start handler.
    dp.include_router(private_panel.router)
    dp.include_router(start.router)
    dp.include_router(moderation.router)
    dp.include_router(admin.router)
    dp.include_router(profile.router)
    dp.include_router(economy.router)
    dp.include_router(games.router)
    dp.include_router(shop.router)
    # Keep natural-language matching last so existing pending inputs and game turns win first.
    dp.include_router(natural.router)
    dp.chat_member.register(
        welcome_new_members,
        ChatMemberUpdatedFilter(JOIN_TRANSITION),
    )
    return dp


async def run_webhook(bot: Bot, dp: Dispatcher, settings) -> None:
    if not settings.public_url:
        raise RuntimeError(
            "Webhook mode requires PUBLIC_URL or RENDER_EXTERNAL_HOSTNAME."
        )

    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/healthz", health_check)

    webhook_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=settings.webhook_secret,
    )
    webhook_handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    runner = web.AppRunner(app)
    try:
        await runner.setup()
        site = web.TCPSite(runner, host="0.0.0.0", port=settings.port)
        await site.start()

        webhook_url = f"{settings.public_url}{WEBHOOK_PATH}"
        await bot.set_webhook(
            url=webhook_url,
            secret_token=settings.webhook_secret,
            allowed_updates=dp.resolve_used_update_types(),
            drop_pending_updates=False,
        )
        logging.info("VORTEX BOT webhook is listening at %s", webhook_url)
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    settings = load_settings()
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    db = Database(settings.database_path)
    await db.connect()
    await initialize_shop(db)
    dp = create_dispatcher(db, settings.owner_ids)
    try:
        await notify_audit_ready(bot, db, settings.owner_ids)
    except Exception:
        logging.exception("Readiness notification failed; continuing bot startup")

    try:
        me = await bot.get_me()
        private_commands = [
            BotCommand(command="start", description="Открыть личный кабинет"),
            BotCommand(command="profile", description="Посмотреть свой профиль"),
            BotCommand(command="help", description="Помощь"),
        ]
        group_commands = [
            BotCommand(command="start", description="Открыть меню"),
            BotCommand(command="help", description="Помощь и список команд"),
            BotCommand(command="profile", description="Профиль участника (ответом)"),
            BotCommand(command="rep", description="Выдать репутацию (ответом)"),
            BotCommand(command="toprep", description="Топ репутации группы"),
            BotCommand(command="topactivity", description="Топ активности группы"),
            BotCommand(command="balance", description="Баланс участника (ответом)"),
            BotCommand(command="daily", description="Получить ежедневную награду"),
            BotCommand(command="pay", description="Перевести V-coins (ответом)"),
            BotCommand(command="exchange", description="Обменять игровые очки на V-coins"),
            BotCommand(command="shop", description="Открыть магазин предметов"),
            BotCommand(command="inventory", description="Мой инвентарь"),
            BotCommand(command="buyitem", description="Купить предмет"),
            BotCommand(command="useitem", description="Использовать предмет"),
            BotCommand(command="giftitem", description="Подарить предмет (ответом)"),
            BotCommand(command="sellitem", description="Выставить предмет на рынок"),
            BotCommand(command="market", description="Объявления игроков"),
            BotCommand(command="buylisting", description="Купить лот на рынке"),
            BotCommand(command="topmoney", description="Топ богачей группы"),
            BotCommand(command="games", description="Открыть игровой зал"),
            BotCommand(command="guessgame", description="Начать игру Угадай число"),
            BotCommand(command="guess", description="Сделать ход в игре"),
            BotCommand(command="topgames", description="Рейтинг игр группы"),
            BotCommand(command="stats", description="Статистика группы"),
        ]
        admin_commands = group_commands + [
            BotCommand(command="warn", description="Выдать предупреждение (ответом)"),
            BotCommand(command="warnings", description="Посмотреть предупреждения (ответом)"),
            BotCommand(command="clearwarns", description="Очистить предупреждения (ответом)"),
            BotCommand(command="mute", description="Ограничить пользователя (ответом)"),
            BotCommand(command="unmute", description="Снять ограничение (ответом)"),
            BotCommand(command="kick", description="Исключить пользователя (ответом)"),
            BotCommand(command="ban", description="Заблокировать пользователя (ответом)"),
            BotCommand(command="unban", description="Разблокировать по ID"),
        ]
        await bot.set_my_commands(private_commands, scope=BotCommandScopeAllPrivateChats())
        await bot.set_my_commands(group_commands, scope=BotCommandScopeAllGroupChats())
        await bot.set_my_commands(admin_commands, scope=BotCommandScopeAllChatAdministrators())
        logging.info("VORTEX BOT starting as @%s in %s mode", me.username, settings.mode)

        if settings.mode == "webhook":
            await run_webhook(bot, dp, settings)
        else:
            await bot.delete_webhook(drop_pending_updates=False)
            await dp.start_polling(
                bot,
                allowed_updates=dp.resolve_used_update_types(),
            )
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
