"""Refunds at the payment gateway (card / e-wallet). Called by the nightly settlement job, not by the web UI.

The shop-side refund record (what staff create from an order page) is a separate concept: see the
adjustments module of orders. A gateway refund here is the money movement that follows it.
"""
import time

GATEWAY_FEES_BP = {"card": 120, "ewallet": 80}      # basis points kept by the gateway


class GatewayError(RuntimeError):
    pass


def gateway_refund_amount(amount_minor, method):
    """Amount the customer actually receives after the gateway fee (minor units, rounded down)."""
    fee = amount_minor * GATEWAY_FEES_BP.get(method, 0) // 10000
    return amount_minor - fee


def queue_gateway_refund(conn, refund_id, method):
    row = conn.execute("SELECT * FROM refunds WHERE id=?", (refund_id,)).fetchone()
    if row is None:
        raise GatewayError("refund not found")
    if row["currency"] not in ("VND", "USD"):
        raise GatewayError(f"currency {row['currency']!r} not supported by gateway")
    conn.execute("CREATE TABLE IF NOT EXISTS gateway_queue (refund_id INTEGER, method TEXT, amount_minor INTEGER, "
                 "queued_ts INTEGER)")
    conn.execute("INSERT INTO gateway_queue VALUES (?,?,?,?)",
                 (refund_id, method, gateway_refund_amount(row["amount_minor"], method), int(time.time())))
    conn.commit()
