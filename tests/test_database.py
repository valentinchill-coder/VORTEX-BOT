import tempfile
import unittest
from pathlib import Path

from database.db import Database


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.temp_dir.name) / "test.db"))
        await self.db.connect()

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    async def test_activity_profile_and_stats(self):
        await self.db.register_message(-1001, 10, "tester", "Test User")
        await self.db.register_message(-1001, 10, "tester", "Test User")
        profile = await self.db.get_profile(-1001, 10)
        self.assertEqual(profile["user"]["message_count"], 2)
        await self.db.add_warning(-1001, 10, 99, "test")
        await self.db.log_event(-1001, "antiflood")
        stats = await self.db.chat_stats(-1001)
        self.assertEqual(stats["users"], 1)
        self.assertEqual(stats["messages"], 2)
        self.assertEqual(stats["warnings"], 1)
        self.assertEqual(stats["antiflood"], 1)

    async def test_reputation_once_per_day(self):
        self.assertTrue(await self.db.give_reputation(-1001, 20, 10))
        self.assertFalse(await self.db.give_reputation(-1001, 20, 10))
        self.assertTrue(await self.db.give_reputation(-1001, 20, 11))
        profile = await self.db.get_profile(-1001, 20)
        self.assertEqual(profile["reputation"], 2)

    async def test_daily_reward_is_idempotent(self):
        claimed, balance = await self.db.claim_daily(-1001, 10)
        self.assertTrue(claimed)
        self.assertEqual(balance, 100)
        claimed_again, balance_again = await self.db.claim_daily(-1001, 10)
        self.assertFalse(claimed_again)
        self.assertEqual(balance_again, 100)

    async def test_transfer_is_atomic_and_checks_balance(self):
        await self.db.claim_daily(-1001, 10)
        success, remaining = await self.db.transfer(-1001, 10, 20, 60)
        self.assertTrue(success)
        self.assertEqual(remaining, 40)
        self.assertEqual(await self.db.get_balance(-1001, 10), 40)
        self.assertEqual(await self.db.get_balance(-1001, 20), 60)
        failed, unchanged = await self.db.transfer(-1001, 10, 20, 50)
        self.assertFalse(failed)
        self.assertEqual(unchanged, 40)
        self.assertEqual(await self.db.get_balance(-1001, 20), 60)


if __name__ == "__main__":
    unittest.main()
