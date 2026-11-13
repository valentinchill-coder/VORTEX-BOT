import unittest

from handlers import economy, games, moderation, profile, shop
from handlers.natural import parse_intent


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

    def test_group_statistics_request_is_recognized(self):
        self.assertEqual(parse_intent("Покажи статистику группы"), "/stats")

    def test_natural_dispatch_targets_exist(self):
        targets = {
            economy: ["balance_command", "daily_command", "pay_command", "top_money_command", "exchange_command"],
            games: ["games_command", "guess_game_command", "top_games_command", "_start_guess", "_start_rps", "_start_quiz"],
            moderation: ["warn", "warnings", "clearwarns", "mute", "unmute", "kick", "ban", "unban"],
            profile: ["profile_command", "reputation_command", "top_reputation_command", "top_activity_command"],
            shop: ["shop_command", "buy_item_command", "inventory_command", "gift_item_command",
                   "use_item_command", "sell_item_command", "market_command", "buy_listing_command"],
        }
        for module, names in targets.items():
            for name in names:
                with self.subTest(module=module.__name__, handler=name):
                    self.assertTrue(callable(getattr(module, name, None)))

    def test_unknown_chat_is_ignored(self):
        self.assertIsNone(parse_intent("Привет всем, как дела?"))


if __name__ == "__main__":
    unittest.main()
