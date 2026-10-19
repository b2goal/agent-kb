"""Daily revenue report. Days are UTC calendar days."""
from datetime import datetime, timezone

from ..orders import service


def order_day(created_ts):
    return datetime.fromtimestamp(created_ts, tz=timezone.utc).strftime("%Y-%m-%d")


def daily_totals(conn):
    """{'YYYY-MM-DD': revenue in minor units} over all orders (single currency report: VND only)."""
    out = {}
    for order in conn.execute("SELECT * FROM orders ORDER BY created_ts"):
        if service.order_currency(order) != "VND":
            continue
        day = order_day(order["created_ts"])
        out[day] = out.get(day, 0) + service.order_total(conn, order)
    return out
