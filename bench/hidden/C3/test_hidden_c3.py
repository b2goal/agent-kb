from shopdemo.orders import service
from shopdemo.reports import daily
from tests.base import DBTest


class HiddenC3(DBTest):
    def test_order_day_is_utc(self):
        self.assertEqual(daily.order_day(1788220800 + 86400 - 1800), "2026-09-01")   # 23:30 UTC
        self.assertEqual(daily.order_day(1788220800 + 86400 + 1800), "2026-09-02")   # 00:30 UTC

    def test_totals_by_utc_day(self):
        totals = daily.daily_totals(self.conn)
        o = service.get_order(self.conn, 1002)
        self.assertIn(daily.order_day(o["created_ts"]), totals)
        self.assertEqual(sum(totals.values()),
                         sum(service.order_total(self.conn, x) for x in self.conn.execute("SELECT * FROM orders")
                             if service.order_currency(x) == "VND"))
