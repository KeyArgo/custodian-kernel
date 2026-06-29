# OpenCode Task: Implement Utility, Scheduling, and Calendar Tools

## Context

You are implementing real execute scripts for Custodian-governed utility tools.
All tools already have stubs at their `scripts/execute.py`. Replace stubs with real code.

## The execute.py contract

- argparse for args, print ONE JSON line, exit 0/1
- Missing credentials → stub response exit 0
- All exceptions caught and returned as {"ok": false, "error": "..."}

## Utility Tools

### `skills/utilities/json-transform/scripts/execute.py`

Args: `--input` (JSON string), `--filter` (jq-like path, e.g. ".name", ".items[0]", ".[] | .id")

Use stdlib only — implement a simple path evaluator:
- "." → return input as-is
- ".key" → input["key"]
- ".key.nested" → input["key"]["nested"]
- ".key[0]" → input["key"][0]
- ".[] | .field" → [item["field"] for item in input]

```python
import json

def apply_filter(data, filt):
    filt = filt.strip()
    if filt == ".":
        return data
    # simple dot-notation walker
    parts = filt.lstrip(".").split(".")
    result = data
    for part in parts:
        if "[" in part:
            key, idx = part.rstrip("]").split("[")
            result = result[key][int(idx)]
        else:
            result = result[part]
    return result
```

Return: `{"ok": true, "tool": "json-transform", "result": transformed}`

### `skills/utilities/base64-encode/scripts/execute.py`

Args: `--input` (string) OR `--file` (path)

```python
import base64
data = open(file).read() if file else input_str
encoded = base64.b64encode(data.encode()).decode()
```
Return: `{"ok": true, "tool": "base64-encode", "encoded": encoded}`

### `skills/utilities/base64-decode/scripts/execute.py`

Args: `--input` (base64 string)

```python
decoded = base64.b64decode(input_str).decode("utf-8", errors="replace")
```
Return: `{"ok": true, "tool": "base64-decode", "decoded": decoded}`

### `skills/utilities/hash-sha256/scripts/execute.py`

Args: `--input` (string) OR `--file` (path)

```python
import hashlib
data = open(file, "rb").read() if file else input_str.encode()
h = hashlib.sha256(data).hexdigest()
```
Return: `{"ok": true, "tool": "hash-sha256", "hash": h}`

### `skills/utilities/currency-convert/scripts/execute.py`

Args: `--amount` (float), `--from` (3-letter code), `--to` (3-letter code)

Use open.er-api.com (free, no key):
```python
r = requests.get(f"https://open.er-api.com/v6/latest/{from_currency}")
rates = r.json()["rates"]
result = amount * rates[to_currency]
```
Return: `{"ok": true, "tool": "currency-convert", "from": from_c, "to": to_c, "amount": amount, "result": result, "rate": rates[to_c]}`

### `skills/utilities/timezone-lookup/scripts/execute.py`

Args: `--datetime` (ISO 8601 string), `--from-tz`, `--to-tz`

Use stdlib `zoneinfo` (Python 3.9+) or `datetime`:
```python
from datetime import datetime
import zoneinfo
dt = datetime.fromisoformat(args.datetime)
if dt.tzinfo is None:
    dt = dt.replace(tzinfo=zoneinfo.ZoneInfo(from_tz))
else:
    dt = dt.astimezone(zoneinfo.ZoneInfo(from_tz))
converted = dt.astimezone(zoneinfo.ZoneInfo(to_tz))
```
Return: `{"ok": true, "tool": "timezone-lookup", "input": ..., "output": converted.isoformat(), "from_tz": from_tz, "to_tz": to_tz}`

### `skills/utilities/url-parse/scripts/execute.py`

Args: `--url`

```python
from urllib.parse import urlparse, parse_qs
p = urlparse(url)
```
Return: `{"ok": true, "tool": "url-parse", "scheme": p.scheme, "host": p.netloc, "path": p.path, "query": parse_qs(p.query), "fragment": p.fragment}`

## Scheduling Tools

Use a simple JSON file-based task queue at `CUSTODIAN_QUEUE_PATH` (default `~/.custodian/queue.json`).

### `skills/scheduling/task-queue-add/scripts/execute.py`

Args: `--task` (description), `--run-at` (ISO datetime, optional), `--tool` (tool name, optional), `--args` (JSON string, optional)

```python
import json, os, uuid
from datetime import datetime, timezone

queue_path = os.environ.get("CUSTODIAN_QUEUE_PATH", os.path.expanduser("~/.custodian/queue.json"))
os.makedirs(os.path.dirname(queue_path), exist_ok=True)

try:
    queue = json.loads(open(queue_path).read()) if os.path.exists(queue_path) else []
except:
    queue = []

entry = {
    "id": str(uuid.uuid4())[:8],
    "task": task,
    "status": "pending",
    "created_at": datetime.now(timezone.utc).isoformat(),
    "run_at": run_at,
    "tool": tool,
    "args": json.loads(args_str) if args_str else {},
}
queue.append(entry)
open(queue_path, "w").write(json.dumps(queue, indent=2))
```
Return: `{"ok": true, "tool": "task-queue-add", "id": entry["id"], "task": task}`

### `skills/scheduling/task-queue-list/scripts/execute.py`

Args: `--status` (pending/completed/all, default pending)

Load queue.json, filter by status.
Return: `{"ok": true, "tool": "task-queue-list", "tasks": filtered_list, "count": n}`

## Cron Tools (stub implementations OK — describe the interface)

### `skills/scheduling/cron-create/scripts/execute.py`

Args: `--name`, `--schedule` (cron expr e.g. "0 9 * * 1"), `--command`

For now: store in `~/.custodian/crons.json`. Real execution requires crontab integration.
Return: `{"ok": true, "tool": "cron-create", "name": name, "schedule": schedule, "note": "registered in ~/.custodian/crons.json; run custodian cron-apply to write to system crontab"}`

### `skills/scheduling/cron-list/scripts/execute.py`

Args: none
Load `~/.custodian/crons.json`.

### `skills/scheduling/cron-delete/scripts/execute.py`

Args: `--name`
Remove from `~/.custodian/crons.json`.

## Calendar Tools (require GOOGLE_CALENDAR_CREDENTIALS_JSON env var)

### `skills/calendar/calendar-event-list/scripts/execute.py`

Args: `--calendar-id` (default "primary"), `--days` (how many days ahead, default 7)

Without google-auth library, use requests + OAuth token from env:
Required: GOOGLE_CALENDAR_ACCESS_TOKEN env var

```python
import requests
from datetime import datetime, timezone, timedelta

now = datetime.now(timezone.utc)
time_max = now + timedelta(days=days)
r = requests.get(
    f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
    headers={"Authorization": f"Bearer {token}"},
    params={"timeMin": now.isoformat(), "timeMax": time_max.isoformat(),
            "singleEvents": True, "orderBy": "startTime", "maxResults": 20}
)
events = r.json().get("items", [])
```
Return: `{"ok": true, "tool": "calendar-event-list", "events": [{...summary, start, end...}]}`

### `skills/calendar/calendar-event-create/scripts/execute.py`

Args: `--title`, `--start` (ISO), `--end` (ISO), `--calendar-id` (default primary), `--description` (optional)

POST to Google Calendar events endpoint.

## After implementing, run the self-tests:

```bash
python3 skills/utilities/base64-encode/scripts/execute.py --input "hello world"
python3 skills/utilities/base64-decode/scripts/execute.py --input "aGVsbG8gd29ybGQ="
python3 skills/utilities/hash-sha256/scripts/execute.py --input "custodian"
python3 skills/utilities/currency-convert/scripts/execute.py --amount 100 --from USD --to EUR
python3 skills/utilities/timezone-lookup/scripts/execute.py --datetime "2026-06-27T09:00:00" --from-tz "America/New_York" --to-tz "Europe/London"
python3 skills/utilities/url-parse/scripts/execute.py --url "https://getcustodian.xyz/triage?pack=refunds"
python3 skills/scheduling/task-queue-add/scripts/execute.py --task "Send weekly report"
python3 skills/scheduling/task-queue-list/scripts/execute.py
```

All of these use stdlib or free public APIs — they should all return ok:true.
