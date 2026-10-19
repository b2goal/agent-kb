import re

SKU_RE = re.compile(r"^[A-Z]{3}-\d{4}$")


def normalize(sku):
    """SKUs are stored upper case as AAA-0000."""
    sku = sku.strip().upper()
    if not SKU_RE.match(sku):
        raise ValueError(f"invalid SKU {sku!r}; expected AAA-0000")
    return sku
