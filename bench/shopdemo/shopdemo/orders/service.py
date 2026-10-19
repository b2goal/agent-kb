"""Reading orders and computing their totals."""
from .. import config


def _apply_discount(subtotal_minor, discount_pct):
    """Percentage discount, rounded half up to the minor unit."""
    if not discount_pct:
        return subtotal_minor
    return (subtotal_minor * (100 - discount_pct) + 50) // 100


def order_currency(order):
    return order["currency"] or config.DEFAULT_CURRENCY


def list_orders(conn, page=1, per_page=None):
    per_page = per_page or config.ORDERS_PER_PAGE
    rows = conn.execute("SELECT o.*, c.name AS customer FROM orders o LEFT JOIN customers c ON c.id = o.customer_id "
                        "ORDER BY o.id DESC LIMIT ? OFFSET ?", (per_page, (page - 1) * per_page)).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    return rows, total


def get_order(conn, order_id):
    return conn.execute("SELECT o.*, c.name AS customer FROM orders o LEFT JOIN customers c ON c.id = o.customer_id "
                        "WHERE o.id=?", (order_id,)).fetchone()


def order_lines(conn, order_id):
    return conn.execute("SELECT * FROM order_lines WHERE order_id=? ORDER BY sku", (order_id,)).fetchall()


def order_subtotal(conn, order_id):
    return sum(l["quantity"] * l["unit_price_minor"] for l in order_lines(conn, order_id))


def order_total(conn, order):
    return _apply_discount(order_subtotal(conn, order["id"]), order["discount_pct"])
