import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiosqlite

from database.db import Database
from handlers.shop import cancel_listing_command, initialize_shop


class ShopMarketTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.temp_dir.name) / "shop.db"))
        await self.db.connect()
        await initialize_shop(self.db)

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    def make_message(self, user_id, listing_id):
        return SimpleNamespace(
            chat=SimpleNamespace(id=-100123, type="supergroup"),
            from_user=SimpleNamespace(id=user_id),
            text=f"/cancel_listing {listing_id}",
            answer=AsyncMock(),
        )

    async def test_seller_can_cancel_listing_and_reclaim_reserved_items(self):
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute(
                "INSERT INTO user_items(chat_id,user_id,item_code,quantity) VALUES(-100123,10,'rose',0)"
            )
            await conn.execute(
                "INSERT INTO market_listings(id,chat_id,seller_id,item_code,quantity,price_each) "
                "VALUES(1,-100123,10,'rose',3,150)"
            )
            await conn.commit()

        message = self.make_message(10, 1)
        await cancel_listing_command(message, self.db)

        async with aiosqlite.connect(self.db.path) as conn:
            listing = await (await conn.execute("SELECT id FROM market_listings WHERE id=1")).fetchone()
            item = await (await conn.execute(
                "SELECT quantity FROM user_items WHERE chat_id=-100123 AND user_id=10 AND item_code='rose'"
            )).fetchone()
        self.assertIsNone(listing)
        self.assertEqual(item[0], 3)
        message.answer.assert_awaited_once()

    async def test_other_user_cannot_cancel_seller_listing(self):
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute(
                "INSERT INTO market_listings(id,chat_id,seller_id,item_code,quantity,price_each) "
                "VALUES(1,-100123,10,'rose',2,150)"
            )
            await conn.commit()

        message = self.make_message(20, 1)
        await cancel_listing_command(message, self.db)

        async with aiosqlite.connect(self.db.path) as conn:
            listing = await (await conn.execute("SELECT seller_id FROM market_listings WHERE id=1")).fetchone()
            item = await (await conn.execute(
                "SELECT quantity FROM user_items WHERE chat_id=-100123 AND user_id=20 AND item_code='rose'"
            )).fetchone()
        self.assertEqual(listing[0], 10)
        self.assertIsNone(item)
        message.answer.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
