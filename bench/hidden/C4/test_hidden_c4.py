import pathlib

from tests.base import DBTest


class HiddenC4(DBTest):
    def test_apply_discount(self):
        from shopdemo.pricing.discounts import apply_discount
        self.assertEqual(apply_discount(10000, 15), 8500)
        self.assertEqual(apply_discount(999, 10), 899)
        self.assertEqual(apply_discount(5000, 0), 5000)

    def test_old_function_gone(self):
        for f in pathlib.Path("shopdemo").rglob("*.py"):
            self.assertNotIn("_apply_discount", f.read_text(encoding="utf-8"), str(f))

    def test_totals_unchanged(self):
        from shopdemo.orders import service
        o = service.get_order(self.conn, 1006)
        sub = service.order_subtotal(self.conn, 1006)
        self.assertEqual(service.order_total(self.conn, o), (sub * (100 - o["discount_pct"]) + 50) // 100)
