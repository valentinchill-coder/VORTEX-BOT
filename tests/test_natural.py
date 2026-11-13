import unittest
from unittest.mock import AsyncMock, Mock, patch

from handlers import economy, games, moderation, profile, shop
from handlers.natural import parse_intent, _dispatch
from handlers.ranks import rank_denial


class NaturalLanguageIntentTests(unittest.TestCase):
    def test_balance(self):
        self.assertEqual(parse_intent("Покажи мой баланс"), "/balance")

    def test_daily_reward(self):
        self.assertEqual(parse_intent("Забери ежедневную награду"), "/daily")

    def test_item_purchase_with_word_quantity(self):
        self.assertEqual(parse_intent("Купи две розы"), "/buyitem rose 2")

    def test_game_specific_request_precedes_generic_game_menu(self):
        self.assertEqual(parse_intent("Начни игру угадай число"), "__game_guess__")

    def test_cancel_market_listing(self):
        self.assertEqual(parse_intent("Сними свой лот 12"), "/cancel_listing 12")

    def test_transfer(self):
        self.assertEqual(parse_intent("Переведи 50 монет"), "/pay 50")

    def test_rank_queries_and_management_phrases(self):
        self.assertEqual(parse_intent("Мой ранг"), "__myrank__")
        self.assertEqual(parse_intent("Покажи ранги"), "__ranks__")
        self.assertEqual(parse_intent("Какие ранги есть в боте"), "__ranks__")
        self.assertEqual(parse_intent("Выдать ранг"), "__rank_usage__")
        self.assertEqual(parse_intent("Выдать ранг 2"), "__rank_set_2__")
        self.assertEqual(parse_intent("Повысить"), "__rank_up__")
        self.assertEqual(parse_intent("Понизить"), "__rank_down__")
        self.assertEqual(parse_intent("Снять ранг"), "__rank_remove__")

    def test_daily_quest_requests_are_recognized(self):
        self.assertEqual(parse_intent("Мои задания"), "/quests")
        self.assertEqual(parse_intent("Задания на сегодня"), "/quests")
        self.assertEqual(parse_intent("Забрать награды за задания"), "/claimquests")

    def test_achievement_request_is_recognized(self):
        self.assertEqual(parse_intent("Покажи достижения"), "/achievements")
        self.assertEqual(parse_intent("Мои достижения"), "/achievements")

    def test_moderation_audit_request_is_recognized(self):
        self.assertEqual(parse_intent("Покажи журнал модерации"), "/audit")

    def test_short_moderation_aliases_are_recognized(self):
        self.assertEqual(parse_intent("Варн"), "/warn")
        self.assertEqual(parse_intent("Варн флуд"), "/warn флуд")
        self.assertEqual(parse_intent("Warn"), "/warn")
        self.assertEqual(parse_intent("Бан"), "/ban")
        self.assertEqual(parse_intent("Замуть"), "/mute 10m")
        self.assertEqual(parse_intent("Мут на 15 минут"), "/mute 15m")
        self.assertEqual(parse_intent("Мут на 2 часа"), "/mute 2h")
        self.assertEqual(parse_intent("Кик"), "/kick")
        self.assertEqual(parse_intent("Размут"), "/unmute")

    def test_group_statistics_request_is_recognized(self):
        self.assertEqual(parse_intent("Покажи статистику группы"), "/stats")

    def test_natural_dispatch_targets_exist(self):
        targets = {
            economy: ["balance_command", "daily_command", "pay_command", "top_money_command", "exchange_command"],
            games: ["games_command", "guess_game_command", "top_games_command", "_start_guess", "_start_rps", "_start_quiz"],
            moderation: ["warn", "warnings", "clearwarns", "mute", "unmute", "kick", "ban", "unban"],
            profile: ["profile_command", "reputation_command", "top_reputation_command", "top_activity_command"],
            shop: ["shop_command", "buy_item_command", "inventory_command", "gift_item_command",
                   "use_item_command", "sell_item_command", "market_command", "buy_listing_command", "cancel_listing_command"],
        }
        for module, names in targets.items():
            for name in names:
                with self.subTest(module=module.__name__, handler=name):
                    self.assertTrue(callable(getattr(module, name, None)))

    def test_unknown_chat_is_ignored(self):
        self.assertIsNone(parse_intent("Привет всем, как дела?"))




class NaturalDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_profile_dispatch_passes_owner_ids(self):
        original = profile.profile_command
        handler = AsyncMock()
        profile.profile_command = handler
        try:
            message = Mock()
            synthetic = Mock()
            message.model_copy.return_value = synthetic
            db = object()
            bot = object()
            owner_ids = frozenset({6537816900})
            await _dispatch(message, "/profile", db, bot, owner_ids)
            handler.assert_awaited_once_with(synthetic, db, owner_ids)
        finally:
            profile.profile_command = original


class ModerationPermissionAuditTests(unittest.IsolatedAsyncioTestCase):
    async def test_denied_moderation_attempt_is_written_to_audit(self):
        message = Mock()
        message.from_user = Mock(id=123)
        message.chat = Mock(id=-1001, type="group")
        message.answer = AsyncMock()
        db = Mock()
        db.log_moderation_action = AsyncMock()
        bot = Mock()

        with patch("handlers.ranks.can_action", new=AsyncMock(return_value=False)):
            allowed = await rank_denial(message, db, bot, frozenset(), "ban")

        self.assertFalse(allowed)
        db.log_moderation_action.assert_awaited_once_with(
            -1001, 123, 0, "permission_denied", "Попытка выполнить действие: ban"
        )
        message.answer.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
