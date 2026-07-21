"""Tests for postgres-query/mysql-query/sqlite-query read-only enforcement.

postgres-query and mysql-query are declared band L0 ("read-only, no
real-world effects") but previously ran `cur.execute(a.query)` verbatim with
no validation at all -- any write/DDL statement would execute. sqlite-query
had a validation step, but it was a blocklist keyed on a handful of write
keywords (INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE/REPLACE) that
missed others entirely (e.g. ATTACH DATABASE).

All three now share the same fix: an allowlist that only permits a single
SELECT or WITH statement, comment- and string-literal-aware so a semicolon
or keyword inside a quoted string/comment doesn't fool the check.

No test coverage existed for any of these scripts before this fix.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

DB_SKILLS = Path(__file__).resolve().parent.parent / "custodian" / "bundled_skills" / "database"
MEMORY_SKILLS = Path(__file__).resolve().parent.parent / "custodian" / "bundled_skills" / "memory"


def _run(script: Path, args: list, env: dict) -> dict:
    result = subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, timeout=10, env=env,
    )
    return json.loads(result.stdout)


# ---- postgres-query / mysql-query ------------------------------------

WRITE_QUERIES = [
    "INSERT INTO users (name) VALUES ('x')",
    "UPDATE users SET name='x'",
    "DELETE FROM users",
    "DROP TABLE users",
    "  select 1; DROP TABLE users;--",  # stacked statement after a valid SELECT
]

READ_QUERIES = [
    "SELECT * FROM users",
    "select id from users where name = 'a;b'",  # semicolon inside a string literal
    "WITH t AS (SELECT 1) SELECT * FROM t",
    "SELECT 1; ",  # single trailing semicolon is fine
]


def _sql_script(name: str) -> Path:
    return DB_SKILLS / name / "scripts" / "execute.py"


def test_postgres_query_rejects_write_statements():
    script = _sql_script("postgres-query")
    for q in WRITE_QUERIES:
        out = _run(script, ["--query", q], env={"POSTGRES_URL": "postgres://x/y"})
        assert out["ok"] is False, q
        assert "only a single read-only SELECT/WITH" in out["error"], q


def test_postgres_query_allows_read_statements_past_validation():
    script = _sql_script("postgres-query")
    for q in READ_QUERIES:
        out = _run(script, ["--query", q], env={"POSTGRES_URL": "postgres://x/y"})
        # No real Postgres in this environment -- proven past validation by
        # the error switching to the driver/connection stage, not rejection.
        assert out["ok"] is False, q
        assert "only a single read-only SELECT/WITH" not in out["error"], q


def test_mysql_query_rejects_write_statements():
    script = _sql_script("mysql-query")
    for q in WRITE_QUERIES:
        out = _run(script, ["--query", q], env={"MYSQL_URL": "mysql://x/y"})
        assert out["ok"] is False, q
        assert "only a single read-only SELECT/WITH" in out["error"], q


def test_mysql_query_allows_read_statements_past_validation():
    script = _sql_script("mysql-query")
    for q in READ_QUERIES:
        out = _run(script, ["--query", q], env={"MYSQL_URL": "mysql://x/y"})
        assert out["ok"] is False, q
        assert "only a single read-only SELECT/WITH" not in out["error"], q


def test_sql_query_stub_without_url():
    out = _run(_sql_script("postgres-query"), ["--query", "SELECT 1"], env={})
    assert out == {
        "ok": False, "stub": True, "tool": "postgres-query",
        "message": "Set POSTGRES_URL to enable",
    }


# ---- sqlite-query ------------------------------------------------------

def _sqlite_run(db_path: Path, sql: str) -> dict:
    script = MEMORY_SKILLS / "sqlite-query" / "scripts" / "execute.py"
    return _run(script, ["--db", str(db_path), "--sql", sql], env={})


def _make_test_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE kv (k TEXT, v TEXT)")
    conn.execute("INSERT INTO kv VALUES ('a', '1')")
    conn.execute("CREATE TABLE secrets (token TEXT)")
    conn.execute("INSERT INTO secrets VALUES ('super-secret-token')")
    conn.commit()
    conn.close()
    return db_path


def test_sqlite_query_rejects_write_statements(tmp_path):
    db_path = _make_test_db(tmp_path)
    for q in ["INSERT INTO kv VALUES ('b','2')", "DROP TABLE kv", "DELETE FROM kv"]:
        out = _sqlite_run(db_path, q)
        assert out["ok"] is False, q
        assert "only a single read-only SELECT/WITH" in out["error"], q


def test_sqlite_query_rejects_attach_database_unlike_old_blocklist():
    """ATTACH was never in the old blocklist -- confirm the allowlist closes it."""
    db_path_dir = Path(__file__).resolve().parent
    out = _sqlite_run(db_path_dir / "nonexistent.db", "ATTACH DATABASE '/etc/passwd' AS x")
    assert out["ok"] is False
    assert "only a single read-only SELECT/WITH" in out["error"]


def test_sqlite_query_allows_plain_select(tmp_path):
    db_path = _make_test_db(tmp_path)
    out = _sqlite_run(db_path, "SELECT k, v FROM kv")
    assert out["ok"] is True
    assert out["rows"] == [["a", "1"]]


def test_sqlite_query_allows_with_cte(tmp_path):
    db_path = _make_test_db(tmp_path)
    out = _sqlite_run(db_path, "WITH t AS (SELECT k FROM kv) SELECT * FROM t")
    assert out["ok"] is True


def test_sqlite_query_rejects_stacked_statement_after_select(tmp_path):
    db_path = _make_test_db(tmp_path)
    out = _sqlite_run(db_path, "SELECT 1; DROP TABLE kv")
    assert out["ok"] is False
    assert "only a single read-only SELECT/WITH" in out["error"]


def test_sqlite_query_tolerates_semicolon_inside_string_literal(tmp_path):
    db_path = _make_test_db(tmp_path)
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO kv VALUES ('a;b', 'v')")
    conn.commit(); conn.close()
    out = _sqlite_run(db_path, "SELECT v FROM kv WHERE k = 'a;b'")
    assert out["ok"] is True
    assert out["rows"] == [["v"]]
