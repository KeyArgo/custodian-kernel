#!/usr/bin/env python3
import argparse, json, os
p = argparse.ArgumentParser()
p.add_argument("--query", required=True)
p.add_argument("--limit", type=int, default=100)
a = p.parse_args()
url = os.environ.get("MYSQL_URL", "")
if not url:
    print(json.dumps({"ok": False, "stub": True, "tool": "mysql-query", "message": "Set MYSQL_URL to enable"})); exit(0)
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
