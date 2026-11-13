import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from aiogram.types import Chat, Message, User

from middlewares.antiflood import AntiFloodMiddleware, contains_blocked_word


class AntiFloodActivityTests(unittest.IsolatedAsyncioTestCase):
    async def test_flooded_message_is_deleted_and_not_counted_as_activity(self):
        middleware = AntiFloodMiddleware(limit=6, window=8.0)
        db = AsyncMock()
        db.add_warning.return_value = 1
        bot = AsyncMock()
        handler = AsyncMock(return_value=None)
        user = User(id=10, is_bot=False, first_name="Tester")
        chat = Chat(id=-1001, type="group")

        with patch.object(Message, "delete", new_callable=AsyncMock) as delete:
            for message_id in range(1, 8):
                message = Message(
                    message_id=message_id,
                    date=datetime.now(timezone.utc),
                    chat=chat,
                    from_user=user,
                    text=f"message {message_id}",
                )
                await middleware(handler, message, {"db": db, "bot": bot})

        self.assertEqual(db.register_message.await_count, 6)
        self.assertEqual(handler.await_count, 6)
        db.add_warning.assert_awaited_once()
        db.log_event.assert_awaited_once_with(-1001, "antiflood")
        delete.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()


class BlockedWordMatchingTests(unittest.TestCase):
    def test_blocked_word_matching_uses_word_boundaries(self):
        self.assertTrue(contains_blocked_word("This is BAD phrase!", ["bad phrase"]))
        self.assertTrue(contains_blocked_word("идиот, хватит", ["идиот"]))
        self.assertFalse(contains_blocked_word("class assignment", ["ass"]))
        self.assertFalse(contains_blocked_word("badly phrased", ["bad phrase"]))

