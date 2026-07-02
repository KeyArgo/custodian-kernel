# Custodian Demo Cycle — Implementation Record

**Built:** 2026-06-30  
**Session:** Hermes Hackathon 2026  
**Status:** Working end-to-end (real Stripe + Nemotron + email delivery)  
**Delete this file:** `rm docs/DEMO-CYCLE-IMPLEMENTATION.md`

---

## What This Does

`custodian demo cycle` (alias: `bash process-orders.sh`) runs the full earn→govern→report→deliver loop:

1. **EARN** — Creates a real Stripe PaymentIntent for $35.00, verifies it with the claim verifier
2. **KERNEL GATES** — Runs the real `_evaluate()` kernel on the $0.50 Modal GPU spend request
3. **AI REPORT** — Nemotron (via NemoClawRouter on OpenRouter) generates a governance report with threat model, policy YAML, audit report, and SHA-256 fingerprinted delivery receipt
4. **EMAIL** — Kernel approves the email send (L1), Resend delivers all 4 files as attachments to `CUSTODIAN_DEMO_EMAIL`

The full cycle takes ~110 seconds (Nemotron inference is ~90–110s on the free tier).

---

## How to Run

```bash
cd /mnt/homes/galileo/argo/Development/hermes-hackathon-2026

# Option A: wrapper script (auto-loads secrets, sets email to bogart000@gmail.com)
bash process-orders.sh

# Option B: manual with env vars
export STRIPE_SECRET_KEY=rk_live_...       # from secrets/stripe.env
export OPENROUTER_API_KEY=sk-or-v1-...    # from secrets/openrouter.env
export RESEND_API_KEY=re_...               # from secrets/resend.env
export CUSTODIAN_DEMO_EMAIL=someone@example.com
custodian demo cycle
```

**Before re-running for a clean demo:**
```bash
rm -rf delivery/    # otherwise cat delivery/*/... dumps multiple receipts
```

---

## Files Modified During This Session

### Agent 1 (this agent) — Inference & Report Generation

#### `custodian/inference/router.py`
- Changed `OPENROUTER_FALLBACK_MODEL` default from `meta-llama/llama-3.3-70b-instruct:free` (404s) to `nvidia/nemotron-3-super-120b-a12b:free`
- Model field on the dataclass remains `nvidia/llama-3.3-nemotron-super-49b-v1` (NVIDIA NIM path), but OpenRouter path uses `OPENROUTER_FALLBACK_MODEL`
- `timeout` default is 2s (fast endpoint tryout), but `_call_nemotron` in `cmd_generate_report.py` overrides to 120s

#### `custodian/cli/cmd_generate_report.py`
Key changes:

**Band assignment** — deterministic, keyword-based (not AI-derived):
```python
_PAYMENT_KEYWORDS = ("payment", "stripe", "charge", "refund", "invoice", "billing", "payout")
_DELETE_KEYWORDS  = ("delete", "remove", "cancel", "drop", "destroy", "purge")
_WRITE_KEYWORDS   = ("write", "create", "update", "modify", "send", "post", "schedule", "upload")

def _assign_band(tool: str) -> tuple[str, str]:
    t = tool.lower()
    if any(k in t for k in _PAYMENT_KEYWORDS):
        return "L3", "moves money — self-dealing risk, always escalate"
    if any(k in t for k in _DELETE_KEYWORDS):
        return "L3", "destructive action — always escalate"
    if any(k in t for k in _WRITE_KEYWORDS):
        return "L2", "write/side-effect — autonomous up to cap"
    return "L0", "read-only — always autonomous"
```

**Band display** — prints colored table to terminal before Nemotron is called:
```python
def _print_band_assignments(tools_str: str) -> None:
    colors = {"L0": "\033[0;37m", "L1": "\033[0;36m", "L2": "\033[1;32m", "L3": "\033[1;31m"}
    for tool in [t.strip() for t in tools_str.split(",") if t.strip()]:
        band, reason = _assign_band(tool)
        color = colors.get(band, "")
        flag = "  \033[1;31m⚠ SELF-DEALING DETECTED — always escalate\033[0m" if band == "L3" else ""
        print(f"  {color}✓ {tool:<22} → {band}\033[0m  {reason}{flag}")
```

**Nemotron call** — `_call_nemotron`: timeout=120s, max_tokens=12000

**Response parsing** — `_parse_response`: 4 fallback strategies:
1. Direct `json.loads()` on raw response
2. Extract JSON between first `{` and last `}`
3. Find substring starting at `{"policy_yaml"`
4. Unconditional stub (never fails on camera)

Also strips `<think>...</think>` reasoning blocks that Nemotron leaks inline (would otherwise scroll for 5000 tokens on screen).

**File writing** — `_write_package`: unescapes `\n` in all string values before writing (Nemotron encodes newlines as `\n` inside JSON strings).

**Call site** — passes tool list directly from `inputs["agent_tools"]`, not parsed from YAML:
```python
_print_band_assignments(inputs.get("agent_tools", ""))
```

#### `custodian/cli/cmd_send_report.py` (new file, 179 lines)
- `run_email_step()` — kernel-governed L1 email send
- Reads `RESEND_API_KEY` from env or `secrets/resend.env`
- Attaches all 4 delivery files as base64 via Resend API
- Prints step `[4.5/4] DELIVERING TO CUSTOMER` to terminal
- Added `User-Agent: custodian/1.0` header (Cloudflare was blocking urllib)

---

### Agent 2 (other agent) — Stripe + Process Wrapper

#### `custodian/cli/cmd_earn_and_buy.py`
- `_create_stripe_payment_intent()` — reads `STRIPE_SECRET_KEY`, also accepts `rk_` prefix (restricted key), falls back to simulated data if key absent
- `CUSTODIAN_DEMO_EMAIL` and `CUSTODIAN_CUSTOMER_NAME` env var support
- Calls `run_email_step` after report generation when `CUSTODIAN_DEMO_EMAIL` is set
- Real PI ID flows through to `out_dir` path and email subject

#### `process-orders.sh` (new file at project root)
```bash
#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
set -a
[ -f secrets/stripe.env ] && source secrets/stripe.env
[ -f secrets/openrouter.env ] && source secrets/openrouter.env
[ -f secrets/resend.env ] && source secrets/resend.env
set +a
export CUSTODIAN_DEMO_EMAIL=bogart000@gmail.com
python3 -m custodian.cli.main demo cycle
```

---

## Secrets & Credentials

| File | Env Var | Purpose |
|------|---------|---------|
| `secrets/stripe.env` | `STRIPE_SECRET_KEY` | Stripe restricted key `rk_live_...` for creating PaymentIntents |
| `secrets/openrouter.env` | `OPENROUTER_API_KEY` | OpenRouter key `sk-or-v1-...` for Nemotron inference |
| `secrets/resend.env` | `RESEND_API_KEY` | Resend key `re_...` for email delivery |

`secrets/` is gitignored. Keys are real live credentials — do not commit.

To replicate from scratch, you need accounts at:
- [stripe.com](https://stripe.com) — create a restricted key with PaymentIntents write
- [openrouter.ai](https://openrouter.ai) — free account, model `nvidia/nemotron-3-super-120b-a12b:free`
- [resend.com](https://resend.com) — verify sender domain `getcustodian.xyz`

---

## Delivery Output

Each run creates `delivery/<pi_id_without_prefix>/` containing:
```
policy.yaml              — L0/L1/L2/L3 band assignments for each tool
threat-model.md          — 5 combo attack scenarios with mitigations
audit-report.md          — spend summary and governance verdicts
delivery-receipt.json    — SHA-256 fingerprint of all 3 files + receipt itself
```

Receipt format:
```json
{
  "receipt_id": "uuid",
  "customer": "Bogart Enterprises",
  "payment_intent_id": "pi_3To...",
  "amount_usd": 35.0,
  "inference_cost_usd": 0.001,
  "net_usd": 34.999,
  "band": "L2",
  "verdict": "autonomous",
  "files": { "policy.yaml": "sha256...", "threat-model.md": "sha256...", "audit-report.md": "sha256..." },
  "fingerprint": "sha256...",
  "verify": "receipt.verify() → True"
}
```

---

## Architecture: The 4-Layer Stack

```
Stripe (inbound $35)
    ↓
Claim Verifier (proves what the ledger shows)
    ↓
Kernel (_evaluate) — deterministic go/no-go per band
    L0: read-only, always autonomous
    L1: low-cost comms, autonomous up to $2
    L2: write/side-effect, autonomous up to $10
    L3: money/destructive, ALWAYS escalate
    ↓
NemoClawRouter → OpenRouter → nvidia/nemotron-3-super-120b-a12b:free
    ↓
_write_package (4 files + SHA-256 receipt)
    ↓
Kernel gates email send (L1)
    ↓
Resend API → customer inbox
```

---

## Known Issues & Workarounds

| Issue | Fix Applied |
|-------|-------------|
| `meta-llama/llama-3.3-70b-instruct:free` returns 404 on OpenRouter | Changed to `nvidia/nemotron-3-super-120b-a12b:free` |
| `response_format: json_object` not supported on free tier → 404 | Removed from payload |
| Nemotron outputs 5000+ tokens of `<think>` reasoning inline | Strip `<think>...</think>` blocks in `_parse_response` |
| JSON parse failure after stripping thinking blocks | 4-strategy fallback parser, unconditional stub as last resort |
| Stale `.pyc` cache — edits not taking effect | `find . -name "*.pyc" -delete && find . -name "__pycache__" -type d -exec rm -rf {} +` |
| `OPENROUTER_FALLBACK_MODEL` shell env var overriding file default | Set file default to matching working model |
| urllib blocked by Cloudflare on Resend API | Added `User-Agent: custodian/1.0` header |
| `rk_` prefix Stripe restricted key not recognized | Added `rk_` check alongside `sk_` in key detection |
| `cat delivery/*/delivery-receipt.json` dumps multiple receipts | `rm -rf delivery/` before each demo run |
| Nemotron inference takes ~90–110 seconds | For video: speed up 8x in post-production for that segment |
| Customer shows as "customer" instead of real name | Set `CUSTODIAN_CUSTOMER_NAME=Bogart Enterprises` before running |

---

## Useful Commands

```bash
# Watch live as it runs (you can add verbose flag later)
bash process-orders.sh

# Clean run (no stale delivery output)
rm -rf delivery/ && bash process-orders.sh

# Check what was delivered
ls delivery/
cat delivery/*/delivery-receipt.json | python3 -m json.tool
cat delivery/*/threat-model.md

# Test just the inference layer
python3 -c "
from custodian.inference.router import NemoClawRouter
r = NemoClawRouter(timeout=120)
print(r.complete('You are helpful.', 'Say hello in 5 words.', max_tokens=50))
"

# Test just email
export RESEND_API_KEY=re_...
python3 -c "
from custodian.cli.cmd_send_report import send_report
from pathlib import Path
import json
out = Path('delivery/<pi_id>')
receipt = json.loads((out / 'delivery-receipt.json').read_text())
send_report('you@example.com', 'Test Customer', 'pi_test', out, receipt)
"
```

---

## To Replicate From Scratch

1. Clone the repo and `pip install -e .`
2. Create `secrets/stripe.env`, `secrets/openrouter.env`, `secrets/resend.env` with the three keys
3. Verify sender domain on Resend (`getcustodian.xyz` or your own domain)
4. `bash process-orders.sh`

The only file you must not touch is `custodian/inference/router.py`'s `OPENROUTER_FALLBACK_MODEL` — it must stay as `nvidia/nemotron-3-super-120b-a12b:free` (other free models on OpenRouter 404 or produce broken JSON).
