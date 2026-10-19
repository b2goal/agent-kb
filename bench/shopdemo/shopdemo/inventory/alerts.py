from .. import config, db

KEY = "inventory.low_stock_threshold"


def get_threshold(conn):
    return int(db.get_setting(conn, KEY, config.DEFAULT_LOW_STOCK_THRESHOLD))


def set_threshold(conn, value):
    value = int(value)
    if value < 0:
        raise ValueError("threshold must be >= 0")
    db.set_setting(conn, KEY, value)


def low_stock_count(conn):
    return conn.execute("SELECT COUNT(*) FROM products WHERE stock <= ?", (get_threshold(conn),)).fetchone()[0]
