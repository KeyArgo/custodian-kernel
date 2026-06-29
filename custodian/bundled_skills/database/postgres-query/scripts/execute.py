#!/usr/bin/env python3
import argparse, json, os
p = argparse.ArgumentParser()
p.add_argument("--query", required=True)
p.add_argument("--limit", type=int, default=100)
a = p.parse_args()
url = os.environ.get("POSTGRES_URL", "")
if not url:
    print(json.dumps({"ok": False, "stub": True, "tool": "postgres-query", "message": "Set POSTGRES_URL to enable"})); exit(0)
try:
    import psycopg2, psycopg2.extras
    conn = psycopg2.connect(url)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(a.query)
    rows = [dict(r) for r in cur.fetchmany(a.limit)]
    conn.close()
    print(json.dumps({"ok": True, "tool": "postgres-query", "rows": rows, "count": len(rows)}))
except ImportError:
    print(json.dumps({"ok": False, "tool": "postgres-query", "error": "pip install psycopg2-binary"}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "postgres-query", "error": str(e)}))
