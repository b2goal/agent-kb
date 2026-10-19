from shopdemo.orders import adjustments, service
from tests.base import DBTest


class OrdersTest(DBTest):
    def test_total_with_discount(self):
        order = service.get_order(self.conn, 1001)
        subtotal = service.order_subtotal(self.conn, 1001)
        self.assertEqual(order["discount_pct"], 10)
        self.assertEqual(service.order_total(self.conn, order), (subtotal * 90 + 50) // 100)

    def test_refund(self):
        rid = adjustments.create_refund(self.conn, 1001, 10000, "Khác")
        self.assertTrue(rid)
        self.assertEqual(adjustments.refunded_total(self.conn, 1001), 10000)

    def test_refund_too_much(self):
        with self.assertRaises(adjustments.RefundError):
            adjustments.create_refund(self.conn, 1001, 10 ** 9, "Khác")
