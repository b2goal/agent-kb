<!-- agent-kb:start (managed by kb; edit via kb add/confirm) -->
# Project notes (agent-kb)
- Tests: `python -m unittest discover -s tests -t .` (standard library only, no pytest)
- Money is stored as integer minor units; CSV/API output uses `money.to_decimal_str`, pages use `money.format_display`
- SKUs are upper case `AAA-0000` (`catalog.sku.normalize`)
- Dates and report days are UTC; CSV/API timestamps are ISO 8601 with a trailing `Z`
- Orders without a currency use `config.DEFAULT_CURRENCY` (VND)
- Run the app: `python seed.py`, then `python -m shopdemo.web.server --port 8800`
- Batch reads: read every file you need in one response; make all edits and run the tests in the next
<!-- agent-kb:end -->
