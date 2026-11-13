import tempfile
import unittest

import aiosqlite
from pathlib import Path

from database.db import Database
from handlers.shop import initialize_shop


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.temp_dir.name) / "test.db"))
        await self.db.connect()
        await initialize_shop(self.db)

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    async def test_moderation_audit_history_is_persisted_and_newest_first(self):
        await self.db.log_moderation_action(-1001, 10, 20, "warn", "spam")
        await self.db.log_moderation_action(-1001, 11, 20, "mute", "10m")
        rows = await self.db.recent_moderation_actions(-1001, limit=10)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["action"], "mute")
        self.assertEqual(rows[0]["actor_id"], 11)
        self.assertEqual(rows[0]["target_id"], 20)
        self.assertEqual(rows[1]["action"], "warn")
        self.assertEqual(rows[1]["details"], "spam")

    async def test_backup_contains_committed_database_data(self):
        backup_path = Path(self.temp_dir.name) / "backup.db"
        await self.db.register_message(-1001, 77, "backup_user", "Backup User")
        await self.db.backup_to(str(backup_path))
        backup_db = Database(str(backup_path))
        profile = await backup_db.get_profile(-1001, 77)
        self.assertEqual(profile["user"]["full_name"], "Backup User")
        self.assertEqual(profile["user"]["message_count"], 1)

    async def test_achievement_stats_aggregate_group_progress(self):
        await self.db.register_message(-1001, 10, "tester", "Test User")
        await self.db.register_message(-1001, 10, "tester", "Test User")
        await self.db.give_reputation(-1001, 10, 11)
        await self.db.add_game_result(-1001, 10, 5, True)
        await self.db.claim_daily(-1001, 10)
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute(
                "INSERT INTO user_items(chat_id,user_id,item_code,quantity) VALUES(?,?,?,?)",
                (-1001, 10, "rose", 3),
            )
            await conn.commit()
        stats = await self.db.achievement_stats(-1001, 10)
        self.assertEqual(stats, {
            "messages": 2,
            "reputation": 1,
            "wins": 1,
            "played": 1,
            "items": 3,
            "balance": 100,
        })

    async def test_daily_quest_progress_and_rewards_are_claimed_once(self):
        for _ in range(10):
            await self.db.register_message(-1001, 10, "tester", "Test User")
        await self.db.add_game_result(-1001, 10, 0, True)
        await self.db.add_game_result(-1001, 10, 0, False)
        await self.db.add_game_result(-1001, 10, 0, False)

        progress = await self.db.daily_quest_progress(-1001, 10)
        self.assertEqual(progress, {"messages": 10, "games": 3, "wins": 1})

        rules = [
            ("messages_10", "messages", 10, 10),
            ("games_3", "games", 3, 15),
            ("win_1", "wins", 1, 10),
        ]
        claimed, balance = await self.db.claim_daily_quest_rewards(-1001, 10, rules)
        self.assertEqual(set(claimed), {"messages_10", "games_3", "win_1"})
        self.assertEqual(balance, 35)
        self.assertEqual(
            await self.db.claimed_daily_quests(-1001, 10),
            {"messages_10", "games_3", "win_1"},
        )

        claimed_again, balance_again = await self.db.claim_daily_quest_rewards(-1001, 10, rules)
        self.assertEqual(claimed_again, [])
        self.assertEqual(balance_again, 35)

    async def test_recent_warnings_returns_reasons_newest_first(self):
        await self.db.add_warning(-1001, 20, 10, "flood")
        await self.db.add_warning(-1001, 20, 11, "advertising")
        rows = await self.db.recent_warnings(-1001, 20, limit=5)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["admin_id"], 11)
        self.assertEqual(rows[0]["reason"], "advertising")
        self.assertEqual(rows[1]["reason"], "flood")

    async def test_warning_expires_and_is_excluded_from_active_count(self):
        await self.db.add_warning(-1001, 20, 10, "temporary warning")
        self.assertEqual(await self.db.warning_count(-1001, 20), 1)
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute(
                "UPDATE warnings SET expires_at='2000-01-01T00:00:00+00:00' WHERE chat_id=? AND user_id=?",
                (-1001, 20),
            )
            await conn.commit()
        self.assertEqual(await self.db.warning_count(-1001, 20), 0)
        rows = await self.db.recent_warnings(-1001, 20)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reason"], "temporary warning")
        self.assertIsNone(rows[0]["revoked_at"])

    async def test_clearing_warnings_preserves_audit_history(self):
        await self.db.add_warning(-1001, 20, 10, "kept in history")
        await self.db.clear_warnings(-1001, 20)
        self.assertEqual(await self.db.warning_count(-1001, 20), 0)
        rows = await self.db.recent_warnings(-1001, 20)
        self.assertEqual(len(rows), 1)
        self.assertIsNotNone(rows[0]["revoked_at"])

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


    async def test_exchange_game_points_is_atomic_and_credits_wallet(self):
        await self.db.add_game_result(-1001, 10, 125, True)
        success, points_left, balance, coins = await self.db.exchange_game_points(
            -1001, 10, 100, rate=10
        )
        self.assertTrue(success)
        self.assertEqual((points_left, balance, coins), (25, 10, 10))
        self.assertEqual(await self.db.get_balance(-1001, 10), 10)
        failed, points_left, balance, coins = await self.db.exchange_game_points(
            -1001, 10, 30, rate=10
        )
        self.assertFalse(failed)
        self.assertEqual((points_left, balance, coins), (25, 10, 0))
        invalid, *_ = await self.db.exchange_game_points(-1001, 10, 11, rate=10)
        self.assertFalse(invalid)

    async def test_transfer_rejects_nonpositive_and_self_transfers(self):
        await self.db.claim_daily(-1001, 10)
        before = await self.db.get_balance(-1001, 10)
        success, remaining = await self.db.transfer(-1001, 10, 20, -50)
        self.assertFalse(success)
        self.assertEqual(remaining, before)
        success, remaining = await self.db.transfer(-1001, 10, 10, 50)
        self.assertFalse(success)
        self.assertEqual(remaining, before)
        self.assertEqual(await self.db.get_balance(-1001, 10), before)

    async def test_moderation_ranks_are_group_scoped_and_removable(self):
        self.assertEqual(await self.db.get_moderation_rank(-1001, 10), 0)
        await self.db.set_moderation_rank(-1001, 10, 3, 99)
        self.assertEqual(await self.db.get_moderation_rank(-1001, 10), 3)
        self.assertEqual(await self.db.get_moderation_rank(-1002, 10), 0)
        await self.db.set_moderation_rank(-1001, 10, 5, 99)
        self.assertEqual(await self.db.get_moderation_rank(-1001, 10), 5)
        await self.db.set_moderation_rank(-1001, 10, 0, 99)
        self.assertEqual(await self.db.get_moderation_rank(-1001, 10), 0)

    async def test_moderation_rank_rejects_reserved_ranks(self):
        with self.assertRaises(ValueError):
            await self.db.set_moderation_rank(-1001, 10, 6, 99)
        with self.assertRaises(ValueError):
            await self.db.set_moderation_rank(-1001, 10, -1, 99)

    async def test_database_rejects_self_reputation_and_negative_game_points(self):
        self.assertFalse(await self.db.give_reputation(-1001, 10, 10))
        with self.assertRaises(ValueError):
            await self.db.add_game_result(-1001, 10, -1, False)

    async def test_game_points_and_leaderboard_are_group_scoped(self):
        total, wins, played = await self.db.add_game_result(-1001, 10, 10, True)
        self.assertEqual((total, wins, played), (10, 1, 1))
        total, wins, played = await self.db.add_game_result(-1001, 10, 5, True)
        self.assertEqual((total, wins, played), (15, 2, 2))
        await self.db.add_game_result(-1002, 10, 50, True)
        await self.db.add_game_result(-1001, 20, 3, False)
        leaders = await self.db.top_games(-1001)
        self.assertEqual(leaders[0], (10, 15, 2, 2))
        self.assertEqual(leaders[1], (20, 3, 0, 1))
        self.assertEqual(len(leaders), 2)


    async def test_chat_settings_are_persistent_and_validated(self):
        defaults = await self.db.get_chat_settings(-1001)
        self.assertEqual(defaults, {"antiflood_enabled": "1", "antiflood_limit": "6", "antiflood_window": "8"})
        await self.db.set_chat_setting(-1001, "antiflood_enabled", "0", 99)
        await self.db.set_chat_setting(-1001, "antiflood_limit", "10", 99)
        await self.db.set_chat_setting(-1001, "antiflood_window", "15", 99)
        settings = await self.db.get_chat_settings(-1001)
        self.assertEqual(settings, {"antiflood_enabled": "0", "antiflood_limit": "10", "antiflood_window": "15"})
        self.assertEqual((await self.db.get_chat_settings(-1002))["antiflood_enabled"], "1")
        with self.assertRaises(ValueError):
            await self.db.set_chat_setting(-1001, "antiflood_limit", "999", 99)


    async def test_group_filters_persist_and_blocked_words_are_normalized(self):
        defaults = await self.db.get_chat_settings(-2001)
        self.assertEqual(defaults["link_filter_enabled"], "0")
        self.assertEqual(defaults["word_filter_enabled"], "0")
        await self.db.set_chat_setting(-2001, "link_filter_enabled", "1", 100)
        await self.db.set_chat_setting(-2001, "word_filter_enabled", "1", 100)
        self.assertEqual((await self.db.get_chat_settings(-2001))["link_filter_enabled"], "1")
        added = await self.db.add_blocked_word(-2001, "  BAD   Phrase ", 100)
        self.assertTrue(added)
        self.assertFalse(await self.db.add_blocked_word(-2001, "bad phrase", 100))
        self.assertEqual(await self.db.list_blocked_words(-2001), ["bad phrase"])
        self.assertTrue(await self.db.remove_blocked_word(-2001, "BAD PHRASE", 100))
        self.assertEqual(await self.db.list_blocked_words(-2001), [])
        with self.assertRaises(ValueError):
            await self.db.add_blocked_word(-2001, "x" * 33, 100)


if __name__ == "__main__":
    unittest.main()
