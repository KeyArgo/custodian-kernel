#!/usr/bin/env python3
import argparse, json, os, sqlite3
KV_PATH = os.environ.get("CUSTODIAN_KV_PATH", os.path.expanduser("~/.custodian/kv.db"))
def get_conn():
    os.makedirs(os.path.dirname(KV_PATH), exist_ok=True)
    c = sqlite3.connect(KV_PATH)
    c.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)")
    c.commit(); return c
def main():
    p = argparse.ArgumentParser(); p.add_argument("--key",required=True)
    a = p.parse_args()
    try:
        conn = get_conn()
        row = conn.execute("SELECT value FROM kv WHERE key=?", (a.key,)).fetchone()
        if row: print(json.dumps({"ok":True,"tool":"kv-get","key":a.key,"value":row[0]}))
        else: print(json.dumps({"ok":False,"tool":"kv-get","error":"key not found","key":a.key}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"kv-get","error":str(e)}))
if __name__=="__main__": main()
