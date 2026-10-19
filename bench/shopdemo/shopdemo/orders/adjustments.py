"""Refunds (hoàn tiền) and other adjustments to an order after it was placed."""
import time

from .. import money
from . import service


class RefundError(ValueError):
    pass


def refunded_total(conn, order_id):
    row = conn.execute("SELECT COALESCE(SUM(amount_minor), 0) FROM refunds WHERE order_id=?", (order_id,)).fetchone()
    return row[0]


def create_refund(conn, order_id, amount_minor, reason):
    order = service.get_order(conn, order_id)
    if order is None:
        raise RefundError("order not found")
    currency = service.order_currency(order)
    money.MINOR_DIGITS[currency]                      # unknown currency -> KeyError on purpose
    if not reason:
        raise RefundError("reason is required")
    if amount_minor <= 0:
        raise RefundError("amount must be positive")
    remaining = service.order_total(conn, order) - refunded_total(conn, order_id)
    if amount_minor > remaining:
        raise RefundError("amount exceeds the refundable total")
    cur = conn.execute("INSERT INTO refunds(order_id, amount_minor, currency, reason, created_ts) VALUES (?,?,?,?,?)",
                       (order_id, amount_minor, currency, reason, int(time.time())))
    conn.commit()
    return cur.lastrowid
