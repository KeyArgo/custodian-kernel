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

_MAX_LIMIT = 1000

# This tool is declared L0 (read-only, no real-world effects). A raw
# caller-supplied filter object passed straight to find() is not safe at
# that trust tier: real MongoDB (unlike some in-memory test doubles) runs
# $where/$function as arbitrary server-side JavaScript, and $expr can
# evaluate aggregation expressions inside a find -- deny any operator key
# not on this explicit read-only allowlist.
_DENIED_OPERATORS = {"$where", "$function", "$accumulator", "$expr"}


def _reject_unsafe_operators(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in _DENIED_OPERATORS:
                raise ValueError(f"operator not allowed in a read-only filter: {key}")
            _reject_unsafe_operators(value)
    elif isinstance(obj, list):
        for item in obj:
            _reject_unsafe_operators(item)


try:
    from pymongo import MongoClient
    filt = json.loads(a.filter)
    _reject_unsafe_operators(filt)
    # limit(0) means "no limit" in MongoDB's cursor semantics, and a
    # negative value is nonsensical -- both must not be allowed to turn a
    # bounded read into an unbounded collection dump.
    limit = max(1, min(a.limit, _MAX_LIMIT))
    client = MongoClient(url, serverSelectionTimeoutMS=5000)
    db = client.get_default_database()
    docs = list(db[a.collection].find(filt, {"_id": 0}).limit(limit))
    client.close()
    print(json.dumps({"ok": True, "tool": "mongodb-find", "collection": a.collection, "docs": docs, "count": len(docs)}))
except ImportError:
    print(json.dumps({"ok": False, "tool": "mongodb-find", "error": "pip install pymongo"}))
except ValueError as e:
    print(json.dumps({"ok": False, "tool": "mongodb-find", "error": str(e)}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "mongodb-find", "error": str(e)}))
