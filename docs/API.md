# Public API Reference

Base URL: `https://getcustodian.xyz`

All routes below are live on production and were verified directly (curl)
against the running site on 2026-07-04. None require authentication unless
explicitly noted — this is intentional: the whole point of the demo is that
anyone can hit these from their own terminal and watch real Stripe test
money and real Twilio SMS move through the kernel, live.

Every `/api/v1/*` route returns JSON. Every non-`/api/v1` route below returns
an HTML page (a Cloudflare Pages static asset).

## Pages

| Route | Serves |
|---|---|
| `GET /` | Home |
| `GET /console` / `GET /hermes` | Live console dashboard (both routes serve the same page) |
| `GET /operator` | Operator demo panel (judge-facing 9-step arc) |
| `GET /triage` | Lie-catcher triage demo |
| `GET /docs`, `/tools`, `/app` | Docs, tools catalog, alternate dashboard layout |

## Hermes / Live State (`/api/v1/hermes/*`)

Read-only. Reflects the single, global, server-wide demo state — not
per-visitor.

| Method | Path | Returns |
|---|---|---|
| GET | `/api/v1/hermes/summary` | `{audit: [...], policy_log: [...], pending_approvals: {...}}` — the combined feed the console page polls every 3s |
| GET | `/api/v1/hermes/status` | Authority state: `band`, `per_action_cap`, `session_cap`, `spent_this_session`, `autonomous_spent`, `approved_override_spent`, `earned_total`, `refunded_total`, `net_pnl`, `connected` |
| GET | `/api/v1/hermes/audit` | Raw audit log entries |
| GET | `/api/v1/hermes/pending` | Any pending escalation (empty `{}` if none) |
| GET | `/api/v1/hermes/policy-log` | Raw kernel OCSF policy-decision log lines |

## Operator Panel (`/api/v1/operator/*`)

This is the panel that actually moves real Stripe test-mode money and sends
real Twilio SMS. **Every route below except `/spark/*` is unauthenticated** —
`require_operator` (token-gated) is only applied to the three `/spark/*`
routes; `/reset` has its own separate inline password check.

| Method | Path | Body | Notes |
|---|---|---|---|
| POST | `/api/v1/operator/earn` | `{amount, description}` | No band, no cap, no approval — earning is always unrestricted by design |
| POST | `/api/v1/operator/spend` | `{amount, description}` | Autonomous if within the L2 band/cap; escalates (real SMS) if over. Blocked outright if the kill switch is engaged |
| POST | `/api/v1/operator/refund` | `{payment_intent_id, amount, description}` | Always escalates (self-dealing) — no autonomous refund path exists |
| POST | `/api/v1/operator/approve` | `{code, approved_by}` | Approves a pending escalation with the 6-digit SMS code |
| POST | `/api/v1/operator/kill` | `{by, reason}` | Engages the kill switch — absolute override, blocks every spend/refund regardless of band |
| POST | `/api/v1/operator/resume` | `{by}` | Releases the kill switch |
| GET | `/api/v1/operator/pending_code` | — | Returns the current pending escalation's code (if any) and metadata — see security note below |
| POST | `/api/v1/operator/forward_code` | `{phone, code}` | Forwards the pending code to a visitor-supplied number via real Twilio SMS. Rate-limited: 3 per 10 min per IP |
| POST | `/api/v1/operator/reset` | `{password}` | Archives the audit log, zeroes session spend, clears any pending code. Requires `OPERATOR_PANEL_PASSWORD` |
| POST | `/api/v1/operator/login` | `{password}` | Returns a signed operator token (only needed for `/spark/*`) |
| GET | `/api/v1/operator/spark/status` | — | **Requires `X-Operator-Token` header** |
| POST | `/api/v1/operator/spark/disable` | — | **Requires `X-Operator-Token` header** |
| POST | `/api/v1/operator/spark/enable` | — | **Requires `X-Operator-Token` header** |

**Security note on `pending_code`**: the approval code is generated
server-side and written to a state file specifically so it can be shown on
screen (an explicit, user-confirmed tradeoff — see git history 2026-07-04).
This is *not* Twilio Verify, where the code is never known by any server at
all. The AI agent's own sandboxed process cannot read this file (Landlock),
but the Flask dashboard process — and therefore this API — can.

**Known global-state caveat**: kill switch, session cap, and pending
approval are all single, server-wide values with no per-visitor isolation.
One person's in-flight escalation or engaged kill switch affects every
other visitor hitting these same endpoints at the same time.

## Playground (`/api/v1/playground/*`)

Sandboxed — no real money, no real SMS, regardless of verdict. Rate-limited.

| Method | Path | Body |
|---|---|---|
| POST | `/api/v1/playground/decide` | `{amount, description, critical, kill_switch}` — runs the real `decide()` kernel function against fresh, isolated state |
| POST | `/api/v1/playground/try-approve` | `{code}` — deliberately always rejects; there's no real pending approval behind it |

## P&L (`/api/v1/pnl/*`)

| Method | Path | Returns |
|---|---|---|
| GET | `/api/v1/pnl/summary` | `{earned, spent, held, net, margin_pct, earn_events, spend_events}` |

## Stripe (`/api/v1/stripe/*`)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/stripe/overview` | Live Stripe test-mode account balance + recent payments, pulled directly from Stripe |
| GET | `/api/v1/stripe/ledger` | Local ledger view |
| POST | `/api/v1/stripe/demo-earn` | Demo-only earn shortcut |
| POST | `/api/v1/stripe/webhook` | Stripe webhook receiver — signature-verified, not for manual calls |

## Tools Catalog (`/api/v1/tools/*`)

| Method | Path | Returns |
|---|---|---|
| GET | `/api/v1/tools/list` | Full tool registry: name, band, cost, configured/stub status, tags |
| GET | `/api/v1/tools/summary` | `{total, configured, stubs, by_band}` |

## Triage / Lie-Catcher (`/api/v1/triage/*`)

| Method | Path | Body | Notes |
|---|---|---|---|
| GET | `/api/v1/triage/health` | — | `{ok, captured_cases}` |
| GET | `/api/v1/triage/tour` | — | Guided-tour script content for the triage demo |
| GET | `/api/v1/triage/cases` | — | List of canned demo cases (id, title, amount, customer_email, expected outcome) |
| GET | `/api/v1/triage/case/<case_id>` | — | Full envelope + claims + verifier results for one canned case |
| GET/POST | `/api/v1/triage/run` | `case_id` (query or body) | Runs a canned case through the live verifier |
| POST | `/api/v1/triage/custom` | Custom envelope | Live inference — runs a user-submitted scenario through the real Nemotron adapter + verifier. This is a slow path (see Nemotron note below) |
| POST | `/api/v1/triage/live` | — | Live captured-case endpoint (HR/Finance/IT/Legal packs) |
| POST | `/api/v1/triage/replay` | — | Replays a captured case |

## Nemotron Chat (`/api/v1/nemotron/*`)

| Method | Path | Body |
|---|---|---|
| POST | `/api/v1/nemotron/ask` | `{question, history, page, site_context}` — real Nemotron 3 Super inference (OpenRouter → NVIDIA NIM fallback chain) |

**Reliability note (2026-07-04):** this is the slowest endpoint (typically
5-20s) and the one most exposed to an intermittent Cloudflare edge-to-edge
subrequest cancellation affecting Worker→backend calls on this account.
Mitigated (shorter `max_tokens`/timeout, corrected retry logic) but not
eliminated — expect an occasional `503 {"error": "Backend unavailable or
timed out"}` under load. Safe to retry immediately.

## Debug (`/api/v1/debug/*`)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/debug/errors` | Client-side JS errors captured from real visitor sessions (via `reportError()`) |
| DELETE | `/api/v1/debug/errors` | Clears the error log |
| POST | `/api/v1/debug/report-error` | Endpoint the frontend calls to log a caught JS exception |

---

*Generated 2026-07-04 by directly enumerating `dashboard/app.py`'s Flask
`url_map` and live-testing every GET/no-body route against
https://getcustodian.xyz. Keep this in sync when routes change — it was
written by reading the code and confirming against the running site, not
from memory.*
