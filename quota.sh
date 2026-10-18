#!/bin/sh
# Print current 5-hour quota utilization (one tiny Haiku call).
D=$(mktemp -d); cd "$D" && env -u CLAUDECODE -u CLAUDE_CODE_SESSION_ID -u CLAUDE_CODE_CHILD_SESSION \
 timeout 90 claude -p "ok" --model haiku --output-format stream-json --verbose --tools "" \
 --no-session-persistence --strict-mcp-config --no-chrome --setting-sources project < /dev/null 2>/dev/null \
 | python3 -c "
import json,sys,datetime
u=None
for l in sys.stdin:
    try: d=json.loads(l)
    except Exception: continue
    if d.get('type')=='rate_limit_event':
        w=d['rate_limit_info'].get('unifiedWindows',{}).get('five_hour',{}); u=w
if u: print('five_hour', u.get('utilization'), 'resets', datetime.datetime.fromtimestamp(u['resetsAt']).astimezone(datetime.timezone(datetime.timedelta(hours=7))).strftime('%H:%M'))
else: print('unknown')
"; rm -rf "$D"
