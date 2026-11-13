import time
from collections import defaultdict, deque
from html import escape

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import Message


class AntiFloodMiddleware(BaseMiddleware):
    """Track group activity and warn every user who exceeds the message limit."""

    def __init__(self, limit: int = 6, window: float = 8.0):
        self.limit = limit
        self.window = window
        self.messages = defaultdict(deque)
        self._checks = 0

    async def __call__(self, handler, event, data):
        if (
            not isinstance(event, Message)
            or not event.from_user
            or event.from_user.is_bot
            or event.chat.type == ChatType.PRIVATE
        ):
            if db:
            try:
                await db.register_message(
                    event.chat.id,
                    event.from_user.id,
                    event.from_user.username,
                    event.from_user.full_name,
                )
            except Exception:
                # Activity tracking must never block normal group messages.
                pass

        return await handler(event, data)

        db = data.get("db")

        key = (event.chat.id, event.from_user.id)
        now = time.monotonic()
        queue = self.messages[key]
        while queue and now - queue[0] > self.window:
            queue.popleft()
        queue.append(now)
        self._checks += 1
        if self._checks % 256 == 0:
            for stale_key, stale_queue in list(self.messages.items()):
                while stale_queue and now - stale_queue[0] > self.window:
                    stale_queue.popleft()
                if not stale_queue:
                    self.messages.pop(stale_key, None)

        if len(queue) > self.limit:
            queue.clear()
            try:
                await event.delete()
            except Exception:
                pass

            if db:
                try:
                    count = await db.add_warning(
                        event.chat.id,
                        event.from_user.id,
                        0,
                        "Автоматическое предупреждение за флуд",
                    )
                    await db.log_event(event.chat.id, "antiflood")
                    bot = data.get("bot")
                    if bot:
                        await bot.send_message(
                            event.chat.id,
                            f"⚠️ {escape(event.from_user.full_name)}, не флуди! "
                            f"Выдано предупреждение. Всего предупреждений: {count}.",
                        )
                except Exception:
                    pass
            return None

        return await handler(event, data)
