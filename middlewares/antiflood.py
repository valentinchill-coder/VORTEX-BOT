import time
from collections import defaultdict, deque

from aiogram import BaseMiddleware
from aiogram.types import Message


class AntiFloodMiddleware(BaseMiddleware):
    """Delete bursts of messages from the same user in the same chat."""

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
            try:
                await event.delete()
            except Exception:
                pass
            return None

        return await handler(event, data)
