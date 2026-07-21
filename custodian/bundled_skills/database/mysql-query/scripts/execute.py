#!/usr/bin/env python3
import argparse, json, os, re
p = argparse.ArgumentParser()
p.add_argument("--query", required=True)
p.add_argument("--limit", type=int, default=100)
a = p.parse_args()
url = os.environ.get("MYSQL_URL", "")
if not url:
    print(json.dumps({"ok": False, "stub": True, "tool": "mysql-query", "message": "Set MYSQL_URL to enable"})); exit(0)

# This tool is declared L0 (read-only, no real-world effects) -- enforce that
# at the query layer with an allowlist (only SELECT/WITH), not a blocklist.
_SQL_COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)


def _is_read_only_select(sql):
    stripped = _SQL_COMMENT.sub(" ", sql)
    no_strings = re.sub(r"'(?:[^']|'')*'", "''", stripped)
    no_strings = re.sub(r'"(?:[^"]|"")*"', '""', no_strings)
    trimmed = no_strings.strip()
    body = trimmed[:-1] if trimmed.endswith(";") else trimmed
    if ";" in body:
        return False
    m = re.match(r"\s*(\w+)", trimmed)
    return bool(m) and m.group(1).upper() in ("SELECT", "WITH")


if not _is_read_only_select(a.query):
    print(json.dumps({"ok": False, "tool": "mysql-query", "error": "only a single read-only SELECT/WITH statement is allowed"})); exit(0)
try:
    import pymysql, pymysql.cursors
    conn = pymysql.connect(read_default_file=None, **pymysql.parse_url(url), cursorclass=pymysql.cursors.DictCursor)
    with conn.cursor() as cur:
        cur.execute(a.query)
        rows = list(cur.fetchmany(a.limit))
    conn.close()
    print(json.dumps({"ok": True, "tool": "mysql-query", "rows": rows, "count": len(rows)}, default=str))
except ImportError:
    print(json.dumps({"ok": False, "tool": "mysql-query", "error": "pip install pymysql"}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "mysql-query", "error": str(e)}))
