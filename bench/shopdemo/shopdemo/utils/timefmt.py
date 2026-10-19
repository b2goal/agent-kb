"""Time helpers. Shop staff work in Vietnam (UTC+7); pages show local time, stored data and reports use UTC."""
from datetime import datetime, timedelta, timezone

SHOP_TZ = timezone(timedelta(hours=7))


def local_day(ts):
    """Calendar day as staff see it (UTC+7). For display only."""
    return datetime.fromtimestamp(ts, tz=SHOP_TZ).strftime("%Y-%m-%d")


def display_time(ts):
    return datetime.fromtimestamp(ts, tz=SHOP_TZ).strftime("%d/%m/%Y %H:%M")


def iso_utc(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
