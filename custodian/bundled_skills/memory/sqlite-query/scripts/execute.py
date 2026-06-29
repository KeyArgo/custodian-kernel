#!/usr/bin/env python3
import argparse, json, sqlite3, re
BLOCKED = re.compile(r"^\s*(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE)", re.IGNORECASE)
def main():
    p = argparse.ArgumentParser(); p.add_argument("--db",required=True); p.add_argument("--sql",required=True)
    a = p.parse_args()
    try:
        if BLOCKED.match(a.sql): raise ValueError("Only SELECT queries are allowed")
        conn = sqlite3.connect(a.db)
        cur = conn.execute(a.sql)
        rows = cur.fetchmany(200)
        cols = [d[0] for d in (cur.description or [])]
        print(json.dumps({"ok":True,"tool":"sqlite-query","columns":cols,"rows":[list(r) for r in rows],"count":len(rows)}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"sqlite-query","error":str(e)}))
if __name__=="__main__": main()
