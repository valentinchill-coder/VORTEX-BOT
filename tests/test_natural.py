import unittest

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

    def test_transfer(self):
        self.assertEqual(parse_intent("Переведи 50 монет"), "/pay 50")

    def test_unknown_chat_is_ignored(self):
        self.assertIsNone(parse_intent("Привет всем, как дела?"))


if __name__ == "__main__":
    unittest.main()
