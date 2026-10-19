"""Coupon codes. A coupon gives a fixed amount off, capped by a percentage of the basket.

Not to be confused with the order-level percentage discount stored on each order (orders.discount_pct).
"""
COUPONS = {"TET2026": {"amount_minor": 50000, "cap_pct": 20, "currency": "VND"},
           "WELCOME5": {"amount_minor": 500, "cap_pct": 10, "currency": "USD"}}


def coupon_discount_amount(code, basket_minor, currency):
    c = COUPONS.get(code.strip().upper())
    if not c or c["currency"] != currency:
        return 0
    return min(c["amount_minor"], basket_minor * c["cap_pct"] // 100)


def basket_after_coupon(code, basket_minor, currency):
    return basket_minor - coupon_discount_amount(code, basket_minor, currency)
