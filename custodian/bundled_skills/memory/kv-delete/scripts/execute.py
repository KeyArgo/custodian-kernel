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
        conn.execute("DELETE FROM kv WHERE key=?", (a.key,)); conn.commit()
        print(json.dumps({"ok":True,"tool":"kv-delete","deleted":a.key}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"kv-delete","error":str(e)}))
if __name__=="__main__": main()
