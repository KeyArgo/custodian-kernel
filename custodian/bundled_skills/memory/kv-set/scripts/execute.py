#!/usr/bin/env python3
import argparse, json, os, sqlite3
from datetime import datetime, timezone
KV_PATH = os.environ.get("CUSTODIAN_KV_PATH", os.path.expanduser("~/.custodian/kv.db"))
def get_conn():
    os.makedirs(os.path.dirname(KV_PATH), exist_ok=True)
    c = sqlite3.connect(KV_PATH)
    c.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)")
    c.commit(); return c
def main():
    p = argparse.ArgumentParser(); p.add_argument("--key",required=True); p.add_argument("--value",required=True)
    a = p.parse_args()
    try:
        conn = get_conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("INSERT OR REPLACE INTO kv (key,value,updated_at) VALUES (?,?,?)", (a.key,a.value,now))
        conn.commit()
        print(json.dumps({"ok":True,"tool":"kv-set","key":a.key,"value":a.value}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"kv-set","error":str(e)}))
if __name__=="__main__": main()
