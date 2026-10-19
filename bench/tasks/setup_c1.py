"""C1: an order without currency crashes the refund (KeyError -> 500). Run inside the work copy."""
import pathlib

p = pathlib.Path("shopdemo/orders/adjustments.py")
s = p.read_text(encoding="utf-8")
assert "    currency = service.order_currency(order)\n" in s
p.write_text(s.replace("    currency = service.order_currency(order)\n", "    currency = order[\"currency\"]\n"),
             encoding="utf-8")
