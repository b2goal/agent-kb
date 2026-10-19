"""Weekly revenue (ISO weeks, local shop time because the weekly meeting reads it as such)."""
from datetime import datetime

from ..orders import service
from ..utils.timefmt import SHOP_TZ


def week_key(ts):
    y, w, _ = datetime.fromtimestamp(ts, tz=SHOP_TZ).isocalendar()
    return f"{y}-W{w:02d}"


def weekly_totals(conn):
    out = {}
    for order in conn.execute("SELECT * FROM orders ORDER BY created_ts"):
        if service.order_currency(order) != "VND":
            continue
        k = week_key(order["created_ts"])
        out[k] = out.get(k, 0) + service.order_total(conn, order)
    return out
