# OpenCode Task: Implement Infrastructure Tools

## Context

You are implementing real execute scripts for Custodian-governed infrastructure tools.
The repo is at the current working directory. Each tool already has a stub `scripts/execute.py`.
Replace the stub with a real implementation following the contract below.

## The execute.py contract

- Accept args via `argparse` (each input as `--key value`)
- Print exactly ONE line of JSON to stdout: `{"ok": true/false, "tool": "<name>", ...}`
- Exit 0 on success, 1 on failure
- If required env var is missing, print stub response and exit 0
- Never raise unhandled exceptions

## Tools to implement

### 1. `skills/web/http-get/scripts/execute.py`

Args: `--url`, `--headers` (JSON string, optional), `--timeout` (int, default 10)

```python
import json, requests
r = requests.get(url, headers=headers, timeout=timeout)
print(json.dumps({"ok": r.ok, "tool": "http-get", "status": r.status_code, "body": r.text[:2000]}))
```

### 2. `skills/web/http-post/scripts/execute.py`

Args: `--url`, `--payload` (JSON string), `--headers` (JSON string, optional)

Same pattern as http-get but POST with json=payload.

### 3. `skills/web/web-scrape/scripts/execute.py`

Args: `--url`, `--selector` (CSS selector, optional — if given, extract matching text only)

```python
import requests
from html.parser import HTMLParser

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self._skip = False
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'nav', 'footer'):
            self._skip = True
    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'nav', 'footer'):
            self._skip = False
    def handle_data(self, data):
        if not self._skip and data.strip():
            self.text.append(data.strip())
```

Return: `{"ok": true, "tool": "web-scrape", "url": url, "text": " ".join(extractor.text)[:3000]}`

### 4. `skills/web/web-search/scripts/execute.py`

Args: `--query`, `--limit` (int, default 5)

Use DuckDuckGo HTML scraping (no API key needed):
```python
r = requests.get("https://html.duckduckgo.com/html/", params={"q": query},
    headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
# parse <a class="result__a"> links and <a class="result__snippet"> descriptions
```
Return: `{"ok": true, "tool": "web-search", "query": query, "results": [{"title": ..., "url": ..., "snippet": ...}]}`

### 5. `skills/web/news-search/scripts/execute.py`

Args: `--query`, `--limit` (default 5)

Same as web-search but append " news" to query and filter for news domains.
Return same shape.

### 6. `skills/files/file-read/scripts/execute.py`

Args: `--path`, `--encoding` (default utf-8), `--limit` (lines, default 500)

Check path is under CUSTODIAN_ALLOWED_READ_DIR (default "/tmp") or is absolute.
Return: `{"ok": true, "tool": "file-read", "path": path, "content": content, "lines": n}`

### 7. `skills/files/file-write/scripts/execute.py`

Args: `--path`, `--content`, `--append` (flag)

Check path is under CUSTODIAN_ALLOWED_WRITE_DIR (default "/tmp").
Return: `{"ok": true, "tool": "file-write", "path": path, "bytes": n}`

### 8. `skills/files/file-list/scripts/execute.py`

Args: `--path`, `--pattern` (glob, default "*")

```python
import glob, os, json
files = glob.glob(os.path.join(path, pattern))
```
Return: `{"ok": true, "tool": "file-list", "path": path, "files": files[:200]}`

### 9. `skills/files/shell-exec/scripts/execute.py`

Args: `--cmd`, `--timeout` (default 10), `--workdir` (default /tmp)

ALLOWLIST = ["ls", "cat", "echo", "pwd", "date", "python3", "pip", "git", "curl", "wget", "jq"]
Check first token of cmd is in allowlist.
```python
import subprocess, shlex
tokens = shlex.split(cmd)
if tokens[0] not in ALLOWLIST:
    print(json.dumps({"ok": False, "error": f"Command '{tokens[0]}' not in allowlist"}))
    sys.exit(1)
r = subprocess.run(tokens, capture_output=True, text=True, timeout=timeout, cwd=workdir)
```
Return: `{"ok": r.returncode == 0, "tool": "shell-exec", "stdout": r.stdout[:2000], "stderr": r.stderr[:500]}`

### 10. `skills/memory/kv-get/scripts/execute.py`
### 11. `skills/memory/kv-set/scripts/execute.py`
### 12. `skills/memory/kv-delete/scripts/execute.py`
### 13. `skills/memory/kv-list/scripts/execute.py`

Use SQLite for the KV store at `CUSTODIAN_KV_PATH` env var (default `~/.custodian/kv.db`).

```python
import sqlite3, os
KV_PATH = os.environ.get("CUSTODIAN_KV_PATH", os.path.expanduser("~/.custodian/kv.db"))
os.makedirs(os.path.dirname(KV_PATH), exist_ok=True)
conn = sqlite3.connect(KV_PATH)
conn.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)")
```

- kv-get: `--key` → SELECT value
- kv-set: `--key`, `--value` → INSERT OR REPLACE
- kv-delete: `--key` → DELETE
- kv-list: `--prefix` (optional) → SELECT key, value WHERE key LIKE prefix%

### 14. `skills/memory/sqlite-query/scripts/execute.py`

Args: `--db` (path to .db file), `--sql` (SELECT only — reject anything starting with INSERT/UPDATE/DELETE/DROP/ALTER)

```python
conn = sqlite3.connect(db_path)
rows = conn.execute(sql).fetchmany(200)
cols = [d[0] for d in cursor.description]
```
Return: `{"ok": true, "tool": "sqlite-query", "columns": cols, "rows": rows, "count": len(rows)}`

### 15. `skills/docker/docker-list/scripts/execute.py`

Args: `--all` (flag, show stopped too)

```python
import subprocess, json
cmd = ["docker", "ps", "--format", "json"]
if args.all: cmd.insert(2, "-a")
r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
containers = [json.loads(line) for line in r.stdout.strip().splitlines() if line]
```
Return: `{"ok": true, "tool": "docker-list", "containers": containers}`

### 16. `skills/docker/docker-logs/scripts/execute.py`

Args: `--container`, `--lines` (default 50)

```python
subprocess.run(["docker", "logs", "--tail", str(lines), container], ...)
```

### 17. `skills/docker/docker-start/scripts/execute.py`
### 18. `skills/docker/docker-stop/scripts/execute.py`

Args: `--container`
Use `docker start <container>` / `docker stop <container>`

### 19. `skills/docker/docker-exec/scripts/execute.py`

Args: `--container`, `--cmd`

```python
subprocess.run(["docker", "exec", container] + shlex.split(cmd), ...)
```

## After implementing, run:

```bash
python3 skills/web/http-get/scripts/execute.py --url https://httpbin.org/get
python3 skills/memory/kv-set/scripts/execute.py --key test --value hello
python3 skills/memory/kv-get/scripts/execute.py --key test
python3 skills/files/file-list/scripts/execute.py --path /tmp
```

All should return `{"ok": true, ...}`.
