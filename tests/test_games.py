import unittest

from handlers.games import _QUIZ, GUESS_ATTEMPTS, GUESS_MAX, GUESS_MIN


class GameBalanceTests(unittest.TestCase):
    def test_guess_game_has_near_even_optimal_win_probability(self):
        # Five binary-search guesses can distinguish at most 31 targets.
        # With 63 equally likely targets, the optimal theoretical chance is 31/63.
        self.assertEqual((GUESS_MIN, GUESS_MAX, GUESS_ATTEMPTS), (1, 63, 5))
        self.assertAlmostEqual(31 / 63, 0.49206349, places=6)

    def test_quiz_questions_have_four_distinct_options_and_valid_answer(self):
        for question, options, correct_index in _QUIZ:
            with self.subTest(question=question):
                self.assertEqual(len(options), 4)
                self.assertEqual(len(set(options)), 4)
                self.assertGreaterEqual(correct_index, 0)
                self.assertLess(correct_index, len(options))


if __name__ == "__main__":
    unittest.main()
