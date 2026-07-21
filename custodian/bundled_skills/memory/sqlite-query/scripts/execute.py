#!/usr/bin/env python3
import argparse, json, sqlite3, re

# This tool is declared L0 (read-only, no real-world effects) -- enforce that
# at the query layer with an allowlist (only SELECT/WITH), not a blocklist. A
# blocklist can always miss a keyword (this one missed ATTACH, PRAGMA, ...);
# an allowlist can't.
_SQL_COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)


def _is_read_only_select(sql):
    stripped = _SQL_COMMENT.sub(" ", sql)
    no_strings = re.sub(r"'(?:[^']|'')*'", "''", stripped)
    no_strings = re.sub(r'"(?:[^"]|"")*"', '""', no_strings)
    trimmed = no_strings.strip()
    body = trimmed[:-1] if trimmed.endswith(";") else trimmed
    if ";" in body:
        return False
    m = re.match(r"\s*(\w+)", trimmed)
    return bool(m) and m.group(1).upper() in ("SELECT", "WITH")


def main():
    p = argparse.ArgumentParser(); p.add_argument("--db",required=True); p.add_argument("--sql",required=True)
    a = p.parse_args()
    try:
        if not _is_read_only_select(a.sql): raise ValueError("only a single read-only SELECT/WITH statement is allowed")
        conn = sqlite3.connect(a.db)
        cur = conn.execute(a.sql)
        rows = cur.fetchmany(200)
        cols = [d[0] for d in (cur.description or [])]
        print(json.dumps({"ok":True,"tool":"sqlite-query","columns":cols,"rows":[list(r) for r in rows],"count":len(rows)}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"sqlite-query","error":str(e)}))
if __name__=="__main__": main()
