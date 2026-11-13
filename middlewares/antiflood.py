import time
from collections import defaultdict, deque
from html import escape

from aiogram import BaseMiddleware
from aiogram.types import Message


class AntiFloodMiddleware(BaseMiddleware):
    """Delete message bursts and warn every offender, including group admins."""

    def __init__(self, limit: int = 6, window: float = 8.0):
        self.limit = limit
        self.window = window
        self.messages = defaultdict(deque)

    async def __call__(self, handler, event, data):
        if not isinstance(event, Message) or not event.from_user or event.from_user.is_bot:
            return await handler(event, data)

        key = (event.chat.id, event.from_user.id)
        now = time.monotonic()
        queue = self.messages[key]

        while queue and now - queue[0] > self.window:
            queue.popleft()

        queue.append(now)

        if len(queue) > self.limit:
            # Reset this burst so one continuous flood does not create a warning
            # for every single message after the threshold.
            queue.clear()

            try:
                await event.delete()
            except Exception:
                pass

            db = data.get("db")
            if db:
                try:
                    count = await db.add_warning(
                        event.chat.id,
                        event.from_user.id,
                        0,
                        "Автоматическое предупреждение за флуд",
                    )
                    await db.log_event(event.chat.id, "antiflood")
                    await event.answer(
                        f"⚠️ {escape(event.from_user.full_name)}, "
                        f"не флуди! Выдано предупреждение. Всего предупреждений: {count}."
                    )
                except Exception:
                    # Keep the middleware from breaking normal message processing
                    # if the database or Telegram API is temporarily unavailable.
                    pass
            return None

        return await handler(event, data)
