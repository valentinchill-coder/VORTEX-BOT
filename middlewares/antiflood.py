import time
import re
from collections import defaultdict, deque
from html import escape

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import Message


def contains_blocked_word(content: str, blocked_words: list[str]) -> bool:
    for word in blocked_words:
        normalized = word.strip().casefold()
        if normalized and re.search(rf"(?<!\w){re.escape(normalized)}(?!\w)", content.casefold()):
            return True
    return False


class AntiFloodMiddleware(BaseMiddleware):
    """Track group activity and warn every user who exceeds the message limit."""

    def __init__(self, limit: int = 6, window: float = 8.0):
        self.limit = limit
        self.window = window
        self.messages = defaultdict(deque)
        self._checks = 0
        self._settings_cache = {}

    async def __call__(self, handler, event, data):
        if (
            not isinstance(event, Message)
            or not event.from_user
            or event.from_user.is_bot
            or event.chat.type == ChatType.PRIVATE
        ):
            return await handler(event, data)

        db = data.get("db")
        now = time.monotonic()
        settings = {"antiflood_enabled": "1", "antiflood_limit": str(self.limit), "antiflood_window": str(int(self.window))}
        cached = self._settings_cache.get(event.chat.id)
        if cached and now - cached[0] < 10:
            settings = cached[1]
        elif db:
            try:
                settings = await db.get_chat_settings(event.chat.id)
                self._settings_cache[event.chat.id] = (now, settings)
            except Exception:
                pass
        limit = max(1, min(50, int(settings.get("antiflood_limit", self.limit))))
        window = max(1, min(60, int(settings.get("antiflood_window", int(self.window)))))
        content = (event.text or event.caption or "").casefold()
        filter_reason = None
        if content and settings.get("link_filter_enabled", "0") == "1":
            if re.search(r"(https?://|www\.|t\.me/|telegram\.me/)", content):
                filter_reason = "filtered_link"
        if content and filter_reason is None and settings.get("word_filter_enabled", "0") == "1" and db:
            try:
                blocked_words = await db.list_blocked_words(event.chat.id)
                if contains_blocked_word(content, blocked_words):
                    filter_reason = "filtered_word"
            except Exception:
                pass
        if filter_reason:
            bot = data.get("bot")
            owners = data.get("owner_ids", frozenset())
            is_admin = event.from_user.id in owners
            if bot and not is_admin:
                try:
                    member = await bot.get_chat_member(event.chat.id, event.from_user.id)
                    is_admin = member.status in ("administrator", "creator")
                except Exception:
                    is_admin = False
            if not is_admin:
                deleted = False
                try:
                    await event.delete()
                    deleted = True
                except Exception:
                    pass
                if db:
                    try:
                        details = "message deleted" if deleted else "delete failed; check bot delete permission"
                        await db.log_moderation_action(event.chat.id, 0, event.from_user.id, filter_reason, details)
                        await db.log_event(event.chat.id, filter_reason)
                    except Exception:
                        pass
                return None

        key = (event.chat.id, event.from_user.id)
        queue = self.messages[key]
        while queue and now - queue[0] > window:
            queue.popleft()
        if settings.get("antiflood_enabled", "1") == "1":
            queue.append(now)
        self._checks += 1
        if self._checks % 256 == 0:
            for stale_key, stale_queue in list(self.messages.items()):
                while stale_queue and now - stale_queue[0] > 60:
                    stale_queue.popleft()
                if not stale_queue:
                    self.messages.pop(stale_key, None)

        if settings.get("antiflood_enabled", "1") == "1" and len(queue) > limit:
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

        # Count only messages that passed the anti-flood check.
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
