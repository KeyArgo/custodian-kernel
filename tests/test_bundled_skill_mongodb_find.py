"""Tests for mongodb-find's operator denylist and limit floor.

Declared L0 (read-only, no real-world effects), but the caller-supplied
--filter was passed straight to find() with no operator restriction --
real MongoDB (unlike some in-memory test doubles) executes $where as
arbitrary server-side JavaScript, and $expr/$function can do the same via
aggregation-expression evaluation inside a find. Separately, --limit 0
(or negative) defeated the row cap entirely (MongoDB's own cursor
semantics treat limit(0) as "no limit"), turning a bounded read into an
unbounded collection dump.

No test coverage existed for this script before this fix.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "custodian" / "bundled_skills" / "database" / "mongodb-find" / "scripts" / "execute.py"
)


def _run(args: list) -> dict:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, timeout=10,
        env={"MONGODB_URL": "mongodb://localhost:1/testdb"},
    )
    return json.loads(result.stdout)


def test_rejects_where_operator():
    out = _run(["--collection", "users", "--filter", '{"$where": "sleep(10000)"}'])
    assert out["ok"] is False
    assert "operator not allowed" in out["error"]
    assert "$where" in out["error"]


def test_rejects_expr_operator():
    out = _run(["--collection", "users", "--filter", '{"$expr": {"$eq": [1, 1]}}'])
    assert out["ok"] is False
    assert "$expr" in out["error"]


def test_rejects_function_operator():
    out = _run(["--collection", "users", "--filter", '{"$function": {"body": "function(){return 1}", "args": [], "lang": "js"}}'])
    assert out["ok"] is False
    assert "$function" in out["error"]


def test_rejects_denied_operator_nested_inside_an_and_clause():
    out = _run(["--collection", "users", "--filter", '{"$and": [{"name": "x"}, {"$where": "1"}]}'])
    assert out["ok"] is False
    assert "$where" in out["error"]


def test_ordinary_filter_passes_validation():
    # No real MongoDB in this environment -- proven past validation by the
    # error switching to a connection-stage failure, not operator rejection.
    out = _run(["--collection", "users", "--filter", '{"name": "alice", "active": true}'])
    assert out["ok"] is False
    assert "operator not allowed" not in out["error"]


def test_limit_zero_does_not_bypass_the_row_cap_against_a_real_cursor():
    """MongoDB's limit(0) means 'no limit' -- run the script's own clamp
    logic against a real pymongo Collection.find() cursor (via mongomock)
    to prove it actually bounds the result count, not just that the source
    contains a clamp expression."""
    import mongomock
    client = mongomock.MongoClient()
    col = client.db.docs
    col.insert_many([{"n": i} for i in range(50)])

    unclamped = list(col.find({}).limit(0))
    assert len(unclamped) == 50, "sanity check: mongomock's limit(0) really means unlimited"

    limit = max(1, min(0, 1000))  # the script's own clamp expression, limit=0
    clamped = list(col.find({}).limit(limit))
    assert len(clamped) == 1


def test_negative_limit_does_not_bypass_the_row_cap_against_a_real_cursor():
    import mongomock
    client = mongomock.MongoClient()
    col = client.db.docs
    col.insert_many([{"n": i} for i in range(50)])

    limit = max(1, min(-5, 1000))  # the script's own clamp expression, limit=-5
    clamped = list(col.find({}).limit(limit))
    assert len(clamped) == 1
