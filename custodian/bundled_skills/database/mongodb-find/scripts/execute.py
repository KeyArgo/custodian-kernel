#!/usr/bin/env python3
import argparse, json, os
p = argparse.ArgumentParser()
p.add_argument("--collection", required=True)
p.add_argument("--filter", default="{}", help="JSON filter")
p.add_argument("--limit", type=int, default=10)
a = p.parse_args()
url = os.environ.get("MONGODB_URL", "")
if not url:
    print(json.dumps({"ok": False, "stub": True, "tool": "mongodb-find", "message": "Set MONGODB_URL to enable"})); exit(0)
try:
    from pymongo import MongoClient
    client = MongoClient(url, serverSelectionTimeoutMS=5000)
    db = client.get_default_database()
    filt = json.loads(a.filter)
    docs = list(db[a.collection].find(filt, {"_id": 0}).limit(a.limit))
    client.close()
    print(json.dumps({"ok": True, "tool": "mongodb-find", "collection": a.collection, "docs": docs, "count": len(docs)}))
except ImportError:
    print(json.dumps({"ok": False, "tool": "mongodb-find", "error": "pip install pymongo"}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "mongodb-find", "error": str(e)}))
