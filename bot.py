import asyncio
import logging

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import ChatMemberUpdated, BotCommand
from aiogram.filters import ChatMemberUpdatedFilter, JOIN_TRANSITION
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from config import load_settings
from database.db import Database
from handlers import start, moderation, admin
from middlewares.antiflood import AntiFloodMiddleware


WEBHOOK_PATH = "/telegram/webhook"


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

    dp.include_router(start.router)
    dp.include_router(moderation.router)
    dp.include_router(admin.router)
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
    dp = create_dispatcher(db, settings.owner_ids)

    try:
        me = await bot.get_me()
        await bot.set_my_commands([
            BotCommand(command="start", description="Открыть главное меню"),
            BotCommand(command="help", description="Помощь и список команд"),
            BotCommand(command="warn", description="Выдать предупреждение (ответом)"),
            BotCommand(command="warnings", description="Посмотреть предупреждения (ответом)"),
            BotCommand(command="clearwarns", description="Очистить предупреждения (ответом)"),
            BotCommand(command="mute", description="Ограничить пользователя (ответом)"),
            BotCommand(command="unmute", description="Снять ограничение (ответом)"),
            BotCommand(command="kick", description="Исключить пользователя (ответом)"),
            BotCommand(command="ban", description="Заблокировать пользователя (ответом)"),
            BotCommand(command="unban", description="Разблокировать по ID"),
            BotCommand(command="stats", description="Статистика группы"),
        ])
        logging.info("VORTEX BOT starting as @%s in %s mode", me.username, settings.mode)

        if settings.mode == "webhook":
            await run_webhook(bot, dp, settings)
        else:
            # Polling and webhooks are mutually exclusive.
            await bot.delete_webhook(drop_pending_updates=False)
            await dp.start_polling(
                bot,
                allowed_updates=dp.resolve_used_update_types(),
            )
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
