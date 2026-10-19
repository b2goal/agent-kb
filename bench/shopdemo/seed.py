"""Create a fresh demo database. Test accounts (local demo only): staff / staff123, admin / admin123.

Run: python seed.py   (writes SHOPDEMO_DB, default ./shopdemo.db)
"""
import os

from shopdemo import config, db

USERS = [("staff", "staff123", "staff"), ("admin", "admin123", "admin")]
CUSTOMERS = ["An Nguyen", "Binh Tran", "Chi Le", "Dung Pham", "Giang Vo", "Hoa Do", "Khanh Bui", "Lan Dang"]
PRODUCTS = [  # sku, name, price (minor units), currency, stock
    ("TEA-0001", "Tra xanh", 45000, "VND", 40), ("TEA-0002", "Tra o long", 120000, "VND", 4),
    ("CUP-0101", "Coc gom", 85000, "VND", 12), ("CUP-0102", "Coc thuy tinh", 60000, "VND", 2),
    ("POT-0201", "Am tra", 350000, "VND", 7), ("POT-0202", "Am dat", 520000, "VND", 15),
    ("BAG-0301", "Tui vai", 30000, "VND", 9), ("BAG-0302", "Hop qua", 25000, "VND", 0),
    ("KIT-0401", "Bo pha tra", 990000, "VND", 5), ("MUG-0501", "Ly su", 70000, "VND", 30),
    ("USD-0601", "Imported tea", 1250, "USD", 6), ("USD-0602", "Imported cup", 899, "USD", 22),
]
BASE_TS = 1788220800          # 2026-09-01T00:00:00Z


def seed(path=None):
    path = path or config.DB_PATH
    if os.path.exists(path):
        os.remove(path)
    conn = db.connect(path)
    conn.executemany("INSERT INTO users(username, password, role) VALUES (?,?,?)", USERS)
    conn.executemany("INSERT INTO customers(name, email) VALUES (?, ?)",
                     [(n, n.lower().replace(" ", ".") + "@example.test") for n in CUSTOMERS])
    conn.executemany("INSERT INTO products VALUES (?,?,?,?,?)", PRODUCTS)
    vnd = [p for p in PRODUCTS if p[3] == "VND"]
    usd = [p for p in PRODUCTS if p[3] == "USD"]
    for i in range(60):
        oid = 1001 + i
        currency = "USD" if oid in (1010, 1020, 1033) else "VND"
        if oid == 1002:
            currency = None                                 # legacy order imported without a currency
        # every 4th order lands 30 minutes before or after midnight UTC
        offset = i * 9 * 3600 + 1800
        if i % 4 == 1:
            offset = (i // 2) * 86400 + 86400 - 1800
        if i % 4 == 3:
            offset = (i // 2) * 86400 + 1800
        discount = (10, 15)[i % 2] if i % 5 == 0 else 0
        conn.execute("INSERT INTO orders VALUES (?,?,?,?,?,?)",
                     (oid, 1 + i % len(CUSTOMERS), currency, ("paid", "shipped", "done")[i % 3], BASE_TS + offset,
                      discount))
        pool = usd if currency == "USD" else vnd
        for k in range(1 + i % 3):
            sku, _, price, _, _ = pool[(i + k * 3) % len(pool)]
            conn.execute("INSERT INTO order_lines VALUES (?,?,?,?)", (oid, sku, 1 + (i + k) % 4, price))
    conn.commit()
    return conn


if __name__ == "__main__":
    seed()
    print(f"seeded {config.DB_PATH}")
