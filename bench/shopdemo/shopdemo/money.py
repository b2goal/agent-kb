"""Money is always stored as an integer number of minor units (VND: dong, USD: cents)."""

MINOR_DIGITS = {"VND": 0, "USD": 2}


def to_decimal_str(minor, currency):
    """Machine format for CSV / API: no thousands separator, '.' as decimal point."""
    digits = MINOR_DIGITS[currency]
    if digits == 0:
        return str(minor)
    sign = "-" if minor < 0 else ""
    whole, frac = divmod(abs(minor), 10 ** digits)
    return f"{sign}{whole}.{frac:0{digits}d}"


def format_display(minor, currency):
    """Human format for pages: VND uses '.' as thousands separator, USD uses '$1,234.50'."""
    if currency == "VND":
        return f"{minor:,}".replace(",", ".") + " đ"
    whole, frac = divmod(minor, 100)
    return f"${whole:,}.{frac:02d}"


def parse_amount(text, currency):
    """Parse what a person typed on a page into minor units."""
    text = text.strip().replace(" ", "").replace("đ", "").replace("$", "")
    if MINOR_DIGITS[currency] == 0:
        return int(text.replace(".", "").replace(",", ""))
    text = text.replace(",", "")
    whole, _, frac = text.partition(".")
    return int(whole or 0) * 100 + int((frac + "00")[:2])
