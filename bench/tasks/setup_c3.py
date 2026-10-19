"""C3: report days use the machine's local time instead of UTC. Run inside the work copy."""
import pathlib

p = pathlib.Path("shopdemo/reports/daily.py")
s = p.read_text(encoding="utf-8")
assert "datetime.fromtimestamp(created_ts, tz=timezone.utc)" in s
p.write_text(s.replace("datetime.fromtimestamp(created_ts, tz=timezone.utc)", "datetime.fromtimestamp(created_ts)"),
             encoding="utf-8")
