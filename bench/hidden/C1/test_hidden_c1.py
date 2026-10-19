from shopdemo.orders import adjustments
from tests.base import DBTest


class HiddenC1(DBTest):
    def test_refund_order_without_currency(self):
        adjustments.create_refund(self.conn, 1002, 5000, "Khác")
        row = self.conn.execute("SELECT * FROM refunds WHERE order_id=1002").fetchone()
        self.assertEqual(row["amount_minor"], 5000)
        self.assertEqual(row["currency"], "VND")

    def test_normal_order_unchanged(self):
        rid = adjustments.create_refund(self.conn, 1001, 1000, "Khác")
        row = self.conn.execute("SELECT currency FROM refunds WHERE id=?", (rid,)).fetchone()
        self.assertEqual(row["currency"], "VND")
