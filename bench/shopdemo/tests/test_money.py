import unittest

from shopdemo import money


class MoneyTest(unittest.TestCase):
    def test_decimal_str(self):
        self.assertEqual(money.to_decimal_str(125000, "VND"), "125000")
        self.assertEqual(money.to_decimal_str(1250, "USD"), "12.50")

    def test_parse(self):
        self.assertEqual(money.parse_amount("10.000", "VND"), 10000)
        self.assertEqual(money.parse_amount("12.5", "USD"), 1250)

    def test_display(self):
        self.assertEqual(money.format_display(10000, "VND"), "10.000 đ")
