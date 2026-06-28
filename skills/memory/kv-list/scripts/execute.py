#!/usr/bin/env python3
import argparse, json, os, sqlite3
KV_PATH = os.environ.get("CUSTODIAN_KV_PATH", os.path.expanduser("~/.custodian/kv.db"))
def get_conn():
    os.makedirs(os.path.dirname(KV_PATH), exist_ok=True)
    c = sqlite3.connect(KV_PATH)
    c.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)")
    c.commit(); return c
def main():
    p = argparse.ArgumentParser(); p.add_argument("--prefix",default="")
    a = p.parse_args()
    try:
        conn = get_conn()
        rows = conn.execute("SELECT key,value FROM kv WHERE key LIKE ? ORDER BY key", (a.prefix+"%",)).fetchall()
        keys = [{"key":r[0],"value":r[1]} for r in rows]
        print(json.dumps({"ok":True,"tool":"kv-list","keys":keys,"count":len(keys)}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"kv-list","error":str(e)}))
if __name__=="__main__": main()
