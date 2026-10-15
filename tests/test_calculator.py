import unittest

from travel_planner.tools.calculator import TripCostCalculatorTool


class CalculatorTests(unittest.TestCase):
    def setUp(self):
        self.tool = TripCostCalculatorTool()

    def calculate(self, amounts, budget=None):
        return self.tool.run(
            expenses=[{"name": f"Статья {i}", "amount": amount} for i, amount in enumerate(amounts)],
            currency="RUB", budget=budget,
        )

    def test_multiple_items_and_fractional_precision(self):
        result = self.calculate(["100.10", "0.20", "2.003"])
        self.assertEqual(result["total"], "102.303")
        self.assertEqual(result["currency"], "RUB")
        self.assertIsNone(result["budget_status"])

    def test_remaining_budget(self):
        result = self.calculate(["0.1", "0.2"], "1")
        self.assertEqual(result["total"], "0.3")
        self.assertEqual(result["budget_status"], "remaining")
        self.assertEqual(result["remaining"], "0.7")
        self.assertEqual(result["over_budget"], "0")

    def test_over_budget(self):
        result = self.calculate(["10.50", "5"], "10")
        self.assertEqual(result["budget_status"], "exceeded")
        self.assertEqual(result["over_budget"], "5.50")
        self.assertEqual(result["remaining"], "0")

    def test_equal_and_zero_budget(self):
        self.assertEqual(self.calculate(["0"], "0")["budget_status"], "equal")

    def test_reject_bad_amounts_and_budgets(self):
        for invalid in ["-1", "abc", "NaN", "Infinity", "-Infinity", float("nan"), float("inf"), True]:
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self.calculate([invalid])
                with self.assertRaises(ValueError):
                    self.calculate(["1"], invalid)

    def test_reject_empty_inputs_and_mixed_currency(self):
        for data in [
            {"expenses": [], "currency": "RUB"},
            {"expenses": [{"name": " ", "amount": "1"}], "currency": "RUB"},
            {"expenses": [{"name": "Hotel", "amount": "1", "currency": "USD"}], "currency": "RUB"},
            {"expenses": [{"name": "Hotel", "amount": "1"}], "currency": " "},
        ]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.tool.run(**data)

    def test_large_and_small_values_are_not_rounded(self):
        result = self.calculate(["123456789012345678901234567890", "0.0000000001"])
        self.assertEqual(result["total"], "123456789012345678901234567890.0000000001")


if __name__ == "__main__":
    unittest.main()
