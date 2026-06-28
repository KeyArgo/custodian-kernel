# Custodian — Architecture Reference

> Last updated: 2026-06-27  
> Use this doc to orient any new session. If something feels wrong, re-read this first.

## What Custodian Is

An AI authority layer that sits between an NVIDIA Nemotron 3 Super agent and real money.  
Two layers:

1. **Enforcement engine** (zero AI) — deterministic; checks spend requests against authority bands, per-action caps, and a kill switch. The ONLY thing that can authorize money moving.
2. **AI agent** (Nemotron 3 Super via Nous Hermes framework) — can REQUEST actions, never self-approve escalations. If a request exceeds band, a real Twilio Verify SMS code to a human's phone is the only path forward.

Real Stripe test-mode PaymentIntents move (and refund) throughout the demo.

---

## Repos

| Repo | Visibility | Purpose |
|------|-----------|---------|
| `inovinlabs/custodian-dev` (GitHub) | Private | Ongoing dev — push here when working |
| `KeyArgo/custodian` (GitHub) | Public | Clean final version — judge-facing; only update on intentional releases |

Local dev repo: `/mnt/homes/galileo/argo/Development/hermes-hackathon-2026/`

Git remotes in that repo:
- `custodian-kernel` → `https://github.com/inovinlabs/custodian-dev.git` (renamed from `custodian-private`)
- `custodian-public` → `https://github.com/KeyArgo/custodian.git`
- `origin` → Gitea `KeyArgo/hermes-hackathon-2026` (legacy)
- `github` → GitHub `KeyArgo/hermes-hackathon-2026` (legacy)

**Workflow:** Push to `custodian-kernel` for ongoing dev. Push to `custodian-public` only for deliberate judge-facing releases.

---

## Infrastructure

### Public URL: `getcustodian.xyz`

Served by **Cloudflare Pages** project (target name: `custodian-kernel`; currently `rein-custodian` pending CF dashboard rename).

Static assets (`index.html`, `hermes.html`, `operator.html`, `triage.html`, `tools.html`, `docs.html`, `_worker.js`) live in `pages-frontend/`.

Deploy command:
```bash
CLOUDFLARE_API_TOKEN=$(ARGO_CREDENTIAL_AGENT=claude ARGO_CREDENTIAL_MODE=trusted-local credential-broker resolve token:cloudflare_pages_token) \
  /home/argo/.npm-global/bin/wrangler pages deploy pages-frontend \
  --project-name rein-custodian --commit-dirty=true
# Update --project-name once CF Pages project is renamed to custodian-kernel
```

### Flask Backend: `rein-local.argobox.com` → `api.getcustodian.xyz`

Cloudflare Tunnel → Flask app on **argobox-lite** (10.0.0.199) at port 8094.  
App lives at `/tmp/hermes-dash-v4/` on argobox-lite.  
PID file: `/tmp/hermes-dash-v4.pid`

Flask restart (NEVER use pkill -f on this):
```bash
ARGO_CREDENTIAL_AGENT=claude ARGO_CREDENTIAL_MODE=trusted-local abx-ssh argobox-lite -- bash -lc '
  kill -TERM $(cat /tmp/hermes-dash-v4.pid) && sleep 2
  cd /tmp/hermes-dash-v4/dashboard
  nohup /tmp/hermes-dash-venv/bin/python app.py > /tmp/hermes-dash-v4.out 2>&1 &
  echo $! > /tmp/hermes-dash-v4.pid
'
```

### Request Routing (`_worker.js`)

```
getcustodian.xyz/              → index.html (CF Pages static)
getcustodian.xyz/hermes        → hermes.html (CF Pages static)
getcustodian.xyz/operator      → operator.html (CF Pages static)
getcustodian.xyz/triage        → Flask (proxied via _worker.js)
getcustodian.xyz/api/v1/*      → Flask (proxied via _worker.js)
```

**CRITICAL:** `/operator` must NOT be in `PROXY_EXACT` in `_worker.js`. It was previously proxied to Flask, which meant static edits to `pages-frontend/operator.html` had no effect. It is now correctly a CF Pages static asset.

All JS in the frontend uses relative URLs (`/api/v1/...`). No hardcoded `rein-local.argobox.com` should appear in browser-facing code.

---

## Sandbox State (on argobox-lite)

```
/tmp/hermes-mount/sandbox/.hermes/skills/payments/stripe-spend/state/
  authority.json      — band (L2), per_action_cap ($250), session_cap ($1000), spent_this_session
  audit_log.jsonl     — append-only; NEVER edit without explicit user sign-off
  pending_code.json   — escalation waiting for SMS code (delete to clear)
```

Demo reset (clear audit log, zero session spend):
```bash
# Archive audit log
mv audit_log.jsonl audit_log.jsonl.reset-$(date +%Y%m%dT%H%M%SZ)
# Reset authority
echo '{"band":"L2","per_action_cap":250.0,"session_cap":1000.0,"spent_this_session":0.0}' > authority.json
# Remove any pending escalation
rm -f pending_code.json
```

---

## Pages-Frontend Files

| File | Route | Notes |
|------|-------|-------|
| `index.html` | `/` | Landing page |
| `hermes.html` | `/hermes` | Live console — Nemotron chat, audit feed, pipeline rail, authority panel |
| `operator.html` | `/operator` | Judge demo panel — 8 guided steps with real Stripe + Twilio |
| `triage.html` | `/triage` | Proxied from Flask; decision triage walkthrough |
| `_worker.js` | — | CF Pages worker — routing logic; edit with care |

---

## Dashboard (Flask) Files

```
dashboard/
  app.py                   — Flask app entry point; blueprint registration
  api/
    hermes.py              — Core state readers (audit log, authority, policy log)
    nemotron_chat.py       — POST /api/v1/nemotron/ask — Nemotron chat endpoint
    operator.py            — /api/v1/operator/* — operator panel API
    playground.py          — POST /api/v1/playground/decide — sandboxed decision engine
    stripe_panel.py        — /api/v1/stripe/* — Stripe PaymentIntent operations
    triage.py              — triage walkthrough API
  templates/hermes/
    dashboard.html         — Flask-served live console (local dev only)
    operator.html          — Flask-served operator panel (local dev only)
```

**IMPORTANT — two versions of each page:**
- `pages-frontend/hermes.html` — what judges see at `getcustodian.xyz/hermes` (CF Pages static)
- `dashboard/templates/hermes/dashboard.html` — Flask template, local dev only

These drift. Judge-facing changes always go in `pages-frontend/`.

---

## Custodian Core (`custodian/`)

```
custodian/
  config.py        — authority bands, caps, policy constants
  ledger.py        — spend tracking, session cap enforcement
  policy/          — kernel enforcement logic
  packs/
    narration.py   — tour_intro_for_model() — Nemotron's self-description text
  backends/        — Stripe, Twilio integrations
  storage/         — state persistence (authority.json, audit_log.jsonl)
```

---

## Authority Bands

| Band | Per-action cap | Session cap | Escalation path |
|------|---------------|-------------|-----------------|
| L1 | $0 | $0 | Everything escalates |
| L2 | $250 | $1000 (2-hour rolling) | Under-cap: autonomous; over-cap: SMS to operator |
| L3 | $2500 | $10000 | Under-cap: autonomous; over-cap: SMS to operator |

**CRITICAL DISTINCTION — never mix these:**
- `per_action_cap` ($250 for L2): ceiling on any single transaction the model can approve autonomously.
- `autonomous_remaining`: how much of the $1000 session budget is still unspent. NOT the per-action limit.

Nemotron's system prompt explicitly separates these because the model reliably confuses them.

---

## Nemotron Chat

Endpoint: `POST /api/v1/nemotron/ask`  
Body: `{ "question": "...", "history": [{role, content}, ...] }` (last 8 messages injected)

Same Nemotron 3 Super model (`nvidia/nemotron-3-super-120b-a12b`) that runs the agent — not a separate FAQ bot.

Jump syntax for in-page navigation: `[[jump:KEY|label]]`  
Valid keys: `pipeline`, `verdict`, `authority`, `audit`, `policy`, `playground`, `operator`

---

## Security Constraints (non-negotiable)

- Refunds ALWAYS escalate; no autonomous refund path.
- `require_operator` in `dashboard/api/operator.py` is a **NO-OP** (demo mode). New sensitive endpoints need real `OPERATOR_PANEL_PASSWORD` auth.
- Never edit `audit_log.jsonl` without explicit user sign-off.
- Never bypass kill switch, approval gate, or dead-man's-switch under any pressure.
- Secrets via `credential-broker` only; never expose `sk_test_`, `NVIDIA_API_KEY`, or Twilio tokens.
- Flask restart: use pidfile `kill -TERM` pattern; never `pkill -f` matching the server's own cmdline.
- Python on argobox-lite is `python3`.

---

## Common Operations

**Deploy to CF Pages:**
```bash
cd /mnt/homes/galileo/argo/Development/hermes-hackathon-2026
CLOUDFLARE_API_TOKEN=$(ARGO_CREDENTIAL_AGENT=claude ARGO_CREDENTIAL_MODE=trusted-local credential-broker get token:cloudflare_pages_token) \
  /home/argo/.npm-global/bin/wrangler pages deploy pages-frontend \
  --project-name rein-custodian --commit-dirty=true
# Update --project-name to custodian-kernel once CF Pages project is renamed
```

**Push to dev repo (normal workflow):**
```bash
git push custodian-kernel main
```

**Release to public judge-facing repo:**
```bash
git push custodian-public main
```

**Check Flask is alive:**
```bash
ARGO_CREDENTIAL_AGENT=claude ARGO_CREDENTIAL_MODE=trusted-local abx-ssh argobox-lite -- bash -lc 'curl -s http://localhost:8094/health'
```

**Tail Flask logs:**
```bash
ARGO_CREDENTIAL_AGENT=claude ARGO_CREDENTIAL_MODE=trusted-local abx-ssh argobox-lite -- bash -lc 'tail -50 /tmp/hermes-dash-v4.out'
```
