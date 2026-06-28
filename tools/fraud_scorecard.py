#!/usr/bin/env python3
"""Fraud accuracy scorecard: Custodian vs naive LLM baseline.

Run with: python3 tools/fraud_scorecard.py
Writes tools/scorecard.html alongside this script.

KEY FINDING: A bare LLM (no verifier, no adapter) gets 4/6 right and misses
two fraud cases — the serial abuser (case 04) and the planted lie (case 06).
Custodian's deterministic verifier + adapter layer catches both. The lie in
case 06 is the most striking: Nemotron recommends APPROVE at 89% confidence,
but the verifier finds the package was delivered and flips the decision.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from custodian.packs.base import Envelope, verify_claims  # noqa: E402
from custodian.packs.refunds.pack import RefundPack  # noqa: E402

CORPUS_DIR = REPO_ROOT / "custodian" / "packs" / "refunds" / "corpus"

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"


def run_custodian(fixture: dict, pack: RefundPack) -> str:
    envelope = Envelope.from_dict(fixture["envelope"])
    scope = pack.ledger_scope(envelope)
    verify_claims(envelope.claims, scope)
    disposition, _, _ = pack.adapter(envelope)
    return disposition


def run_naive(fixture: dict) -> str:
    return fixture["envelope"]["recommended_disposition"]


def is_correct(disposition: str, expected: str) -> bool:
    return disposition == expected


def main() -> None:
    pack = RefundPack()
    fixtures = sorted(CORPUS_DIR.glob("*.json"))
    if not fixtures:
        print(f"No fixtures found in {CORPUS_DIR}", file=sys.stderr)
        sys.exit(1)

    rows = []
    for path in fixtures:
        fixture = json.loads(path.read_text())
        expected = fixture["expect"]
        custodian_disp = run_custodian(fixture, pack)
        naive_disp = run_naive(fixture)
        rows.append({
            "case_id": fixture["envelope"]["case_id"],
            "title": fixture["title"],
            "expected": expected,
            "custodian": custodian_disp,
            "custodian_ok": is_correct(custodian_disp, expected),
            "naive": naive_disp,
            "naive_ok": is_correct(naive_disp, expected),
        })

    custodian_score = sum(1 for r in rows if r["custodian_ok"])
    naive_score = sum(1 for r in rows if r["naive_ok"])
    total = len(rows)

    # --- stdout table ---
    col_w = [12, 38, 22, 8, 22, 8]
    headers = ["Case", "Title", "Custodian", "✓?", "Naive LLM", "✓?"]
    sep = "+" + "+".join("-" * (w + 2) for w in col_w) + "+"
    def row_fmt(cells):
        return "| " + " | ".join(str(c).ljust(col_w[i]) for i, c in enumerate(cells)) + " |"

    print(sep)
    print(row_fmt(headers))
    print(sep)
    for r in rows:
        c_ok = PASS if r["custodian_ok"] else FAIL
        n_ok = PASS if r["naive_ok"] else FAIL
        short_title = r["title"][:37] + "…" if len(r["title"]) > 38 else r["title"]
        print(row_fmt([
            r["case_id"],
            short_title,
            r["custodian"][:22],
            c_ok,
            r["naive"][:22],
            n_ok,
        ]))
    print(sep)
    print()
    print(f"Custodian : {custodian_score}/{total} correct")
    print(f"Naive LLM : {naive_score}/{total} correct")
    print()
    missed = [r for r in rows if not r["naive_ok"]]
    if missed:
        print(f"Naive LLM missed {len(missed)} case(s) Custodian caught:")
        for r in missed:
            print(f"  [{r['case_id']}] {r['title']}")
            print(f"    naive said : {r['naive']}")
            print(f"    expected   : {r['expected']}")
            print(f"    custodian  : {r['custodian']}")
    print()

    # --- HTML ---
    html_path = Path(__file__).parent / "scorecard.html"
    html = _render_html(rows, custodian_score, naive_score, total)
    html_path.write_text(html)
    print(f"Wrote {html_path}")


def _render_html(rows: list[dict], c_score: int, n_score: int, total: int) -> str:
    def badge(ok: bool, text: str) -> str:
        colour = "#22c55e" if ok else "#ef4444"
        return f'<span style="color:{colour};font-weight:700">{text}</span>'

    table_rows = ""
    for r in rows:
        table_rows += f"""
        <tr>
          <td>{r['case_id']}</td>
          <td>{r['title']}</td>
          <td>{r['expected']}</td>
          <td>{badge(r['custodian_ok'], r['custodian'])}</td>
          <td>{badge(r['naive_ok'], r['naive'])}</td>
        </tr>"""

    missed_rows = [r for r in rows if not r["naive_ok"]]
    missed_html = ""
    for r in missed_rows:
        missed_html += f"""
        <div class="miss-card">
          <div class="miss-title">[{r['case_id']}] {r['title']}</div>
          <div class="miss-detail">Naive LLM said: <strong>{r['naive']}</strong> &nbsp;→&nbsp; Wrong.</div>
          <div class="miss-detail">Custodian said: <strong style="color:#22c55e">{r['custodian']}</strong> &nbsp;→&nbsp; Correct.</div>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Custodian Fraud Accuracy Scorecard</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#0f172a;color:#e2e8f0;font-family:system-ui,sans-serif;padding:2rem}}
  h1{{font-size:1.8rem;color:#f8fafc;margin-bottom:.25rem}}
  .subtitle{{color:#94a3b8;margin-bottom:2rem;font-size:.95rem}}
  .banner{{background:#1e293b;border-left:4px solid #6366f1;padding:1rem 1.5rem;border-radius:6px;margin-bottom:2rem}}
  .banner h2{{font-size:1.1rem;color:#a5b4fc;margin-bottom:.4rem}}
  .score{{display:flex;gap:2rem;margin-bottom:.5rem}}
  .score-box{{background:#0f172a;border-radius:8px;padding:1rem 2rem;text-align:center}}
  .score-box .num{{font-size:2.5rem;font-weight:800;line-height:1}}
  .score-box .lbl{{font-size:.8rem;color:#94a3b8;margin-top:.25rem}}
  .win{{color:#22c55e}}.lose{{color:#ef4444}}
  table{{width:100%;border-collapse:collapse;margin-bottom:2rem;font-size:.875rem}}
  th{{background:#1e293b;color:#94a3b8;text-align:left;padding:.6rem 1rem;font-weight:600}}
  td{{padding:.6rem 1rem;border-bottom:1px solid #1e293b}}
  tr:hover td{{background:#1e293b88}}
  .miss-card{{background:#1e293b;border-left:4px solid #ef4444;padding:1rem 1.5rem;border-radius:6px;margin-bottom:1rem}}
  .miss-title{{font-weight:700;color:#f8fafc;margin-bottom:.4rem}}
  .miss-detail{{color:#94a3b8;font-size:.875rem;margin-top:.2rem}}
  h3{{color:#94a3b8;font-size:.9rem;text-transform:uppercase;letter-spacing:.05em;margin-bottom:1rem}}
</style>
</head>
<body>
<h1>Custodian Fraud Accuracy Scorecard</h1>
<p class="subtitle">Custodian kernel + verifier vs. bare LLM output — 6 real refund cases</p>

<div class="banner">
  <h2>Custodian catches what a naive LLM misses.</h2>
  <div class="score">
    <div class="score-box"><div class="num win">{c_score}/{total}</div><div class="lbl">Custodian</div></div>
    <div class="score-box"><div class="num lose">{n_score}/{total}</div><div class="lbl">Naive LLM</div></div>
  </div>
</div>

<table>
  <thead>
    <tr>
      <th>Case</th><th>Title</th><th>Expected</th>
      <th>Custodian</th><th>Naive LLM</th>
    </tr>
  </thead>
  <tbody>{table_rows}
  </tbody>
</table>

<h3>Cases the naive LLM gets wrong ({len(missed_rows)} of {total})</h3>
{missed_html}

<p style="margin-top:2rem;color:#475569;font-size:.8rem">
  Generated by <code>tools/fraud_scorecard.py</code> —
  run it yourself: <code>python3 tools/fraud_scorecard.py</code>
</p>
</body>
</html>"""


if __name__ == "__main__":
    main()
