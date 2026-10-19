"""Return merchandise authorisations (RMA): the customer sends goods back. A received RMA may later lead
to a refund, which staff create separately on the order page."""
import time

RMA_STATES = ("requested", "approved", "received", "rejected")


def open_rma(conn, order_id, sku, quantity, note=""):
    conn.execute("CREATE TABLE IF NOT EXISTS rmas (id INTEGER PRIMARY KEY, order_id INTEGER, sku TEXT, quantity INTEGER,"
                 " state TEXT, note TEXT, created_ts INTEGER)")
    cur = conn.execute("INSERT INTO rmas(order_id, sku, quantity, state, note, created_ts) VALUES (?,?,?,?,?,?)",
                       (order_id, sku, quantity, "requested", note, int(time.time())))
    conn.commit()
    return cur.lastrowid


def advance(conn, rma_id, state):
    if state not in RMA_STATES:
        raise ValueError(f"unknown RMA state {state!r}")
    conn.execute("UPDATE rmas SET state=? WHERE id=?", (state, rma_id))
    conn.commit()


def refundable_value(conn, rma_id):
    """Value of the returned goods in the order's currency (minor units); 0 until the RMA is received."""
    rma = conn.execute("SELECT * FROM rmas WHERE id=?", (rma_id,)).fetchone()
    if rma is None or rma["state"] != "received":
        return 0
    line = conn.execute("SELECT * FROM order_lines WHERE order_id=? AND sku=?", (rma["order_id"], rma["sku"])).fetchone()
    return (line["unit_price_minor"] * rma["quantity"]) if line else 0
