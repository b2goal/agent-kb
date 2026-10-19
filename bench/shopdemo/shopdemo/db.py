import sqlite3

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, role TEXT);
CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY, name TEXT, email TEXT);
CREATE TABLE IF NOT EXISTS products (sku TEXT PRIMARY KEY, name TEXT, price_minor INTEGER, currency TEXT, stock INTEGER);
CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, customer_id INTEGER, currency TEXT, status TEXT,
  created_ts INTEGER, discount_pct INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS order_lines (order_id INTEGER, sku TEXT, quantity INTEGER, unit_price_minor INTEGER);
CREATE TABLE IF NOT EXISTS refunds (id INTEGER PRIMARY KEY, order_id INTEGER, amount_minor INTEGER, currency TEXT,
  reason TEXT, created_ts INTEGER);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""


def connect(path=None):
    conn = sqlite3.connect(path or config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def get_setting(conn, key, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, str(value)))
    conn.commit()
