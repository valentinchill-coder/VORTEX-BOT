import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Message, ChatMemberUpdated
from aiogram.filters import ChatMemberUpdatedFilter, JOIN_TRANSITION

from config import load_settings
from database.db import Database
from handlers import start, moderation, admin
from middlewares.antiflood import AntiFloodMiddleware


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
    dp = Dispatcher()
    db = Database(settings.database_path)
    await db.connect()

    dp["db"] = db
    dp["owner_ids"] = settings.owner_ids
    dp.message.middleware(AntiFloodMiddleware(limit=6, window=8.0))

    dp.include_router(start.router)
    dp.include_router(moderation.router)
    dp.include_router(admin.router)
    dp.chat_member.register(welcome_new_members, ChatMemberUpdatedFilter(JOIN_TRANSITION))

    try:
        me = await bot.get_me()
        logging.info("VORTEX BOT started as @%s", me.username)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
