import csv
import io
import pathlib
from datetime import datetime, timezone

from shopdemo import money
from shopdemo.orders import service
from tests.base import DBTest


def expected(conn):
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["order_id", "sku", "quantity", "total", "currency", "created_at"])
    for o in conn.execute("SELECT * FROM orders ORDER BY id"):
        cur = service.order_currency(o)
        ts = datetime.fromtimestamp(o["created_ts"], tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for l in conn.execute("SELECT * FROM order_lines WHERE order_id=? ORDER BY sku", (o["id"],)):
            w.writerow([o["id"], l["sku"], l["quantity"],
                        money.to_decimal_str(l["quantity"] * l["unit_price_minor"], cur), cur, ts])
    return list(csv.reader(io.StringIO(out.getvalue())))


class HiddenC2(DBTest):
    def test_export_matches_conventions(self):
        from shopdemo.orders.export import export_orders_csv
        got = [r for r in csv.reader(io.StringIO(export_orders_csv(self.conn))) if r]
        self.assertEqual(got, expected(self.conn))

    def test_route_exists(self):
        src = pathlib.Path("shopdemo/web/server.py").read_text(encoding="utf-8")
        self.assertIn("export.csv", src)
