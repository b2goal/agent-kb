"""Loyalty tiers: customers with enough spend get a tier label shown on their profile (no price effect)."""
TIERS = [(0, "Đồng"), (5_000_000, "Bạc"), (20_000_000, "Vàng")]


def tier_for_spend(spend_minor_vnd):
    label = TIERS[0][1]
    for floor, name in TIERS:
        if spend_minor_vnd >= floor:
            label = name
    return label
