from datetime import datetime, timezone

from shopdemo.orders import service
from shopdemo.reports import daily
from tests.base import DBTest


class ReportsTest(DBTest):
    def test_days_are_utc(self):
        expected = {}
        for o in self.conn.execute("SELECT * FROM orders"):
            if service.order_currency(o) != "VND":
                continue
            day = datetime.fromtimestamp(o["created_ts"], tz=timezone.utc).strftime("%Y-%m-%d")
            expected[day] = expected.get(day, 0) + service.order_total(self.conn, o)
        self.assertEqual(daily.daily_totals(self.conn), expected)

    def test_late_evening_order_counts_on_its_utc_day(self):
        order = service.get_order(self.conn, 1006)          # 23:30 UTC
        self.assertEqual(daily.order_day(order["created_ts"]), "2026-09-03")
