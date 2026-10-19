"""Grade a browser task from the app database and the agent's final message.

Usage: python grade_browser.py <task> <db path> <final text file>   -> prints JSON
"""
import json
import re
import sqlite3
import sys

task, db_path, text_path = sys.argv[1:4]
conn = sqlite3.connect(db_path)
text = open(text_path, encoding="utf-8").read()
if task == "B1":
    rows = conn.execute("SELECT amount_minor, reason FROM refunds WHERE order_id=1001").fetchall()
    ok = rows == [(10000, "Khách đổi ý")]
    detail = {"refunds": rows}
elif task == "B2":
    row = conn.execute("SELECT value FROM settings WHERE key='inventory.low_stock_threshold'").fetchone()
    want = conn.execute("SELECT COUNT(*) FROM products WHERE stock <= 5").fetchone()[0]
    ok = bool(row) and row[0] == "5" and str(want) in re.findall(r"\d+", text)
    detail = {"threshold": row[0] if row else None, "expected_badge": want}
else:
    raise SystemExit(f"unknown task {task}")
print(json.dumps({"success": ok, "detail": detail}, ensure_ascii=False))
