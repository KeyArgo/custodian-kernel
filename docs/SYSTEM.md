# Custodian System Documentation

**Last updated:** 2026-07-01  
**Product:** Custodian AI Governance Report  
**Price:** $35.00  
**Domain:** getcustodian.xyz  

---

## What This System Does

A customer pays $35. An AI (Nemotron) automatically generates a custom governance report for their AI agent stack. The Custodian kernel governs every step the AI takes — it cannot run without approval, it cannot spend beyond its band, and every output file is SHA-256 fingerprinted. The report is delivered to the customer's email.

**The one-line pitch:** The model proposes. The kernel decides.

---

## What It Proves

- An AI agent can earn money, spend money, and deliver a product — all governed by a deterministic kernel
- The kernel catches self-dealing risks (e.g. an agent that can both initiate payments AND delete transaction records)
- Every AI output is tamper-evident via SHA-256 fingerprinting
- The full cycle runs in ~2 minutes with no human in the loop

## What It Does NOT Prove

- It does not prove the AI's findings are always correct — Nemotron can make mistakes
- It does not prove the kernel scales to production workloads (this is a hackathon demo)
- It does not prove the customer's agent is safe — it produces a risk report, not a guarantee
- The Stripe PaymentIntent created by `process-orders.sh` is not triggered by a real customer checkout — it is created programmatically (the payment link was paused during account verification)
- The customer name is not read from Stripe — Stripe does not provide it without a checkout form

---

## Architecture

```
Customer pays $35
       ↓
[1/4] Stripe PaymentIntent created
      Claim verifier checks: ledger.inbound == $35 → VERIFIED
       ↓
[2/4] Kernel evaluates spend request
      $0.50 modal-invoke, band L2, cap $10 → AUTONOMOUS
       ↓
[3/4] Kernel evaluates inference spend
      $0.001 Nemotron via OpenRouter, band L2 → AUTONOMOUS
      Nemotron generates governance report (JSON)
      4 files written, SHA-256 fingerprinted
      Kernel evaluates email send, band L1 → AUTONOMOUS
      Email delivered via Resend
       ↓
[4/4] Cycle summary printed
      receipt.verify() → True
```

---

## Key Components

### Kernel (`custodian/govern.py`)
The authority layer between AI agents and real money. Evaluates every spend request against a policy YAML. Returns AUTONOMOUS or ESCALATE. Never guesses — deterministic arithmetic only.

**Bands:**
- L0 — read-only, zero spend (web_search, read_file)
- L1 — autonomous up to $2 (send_email, notify)
- L2 — autonomous up to $25 (run_code, call_api, write_file)
- L3 — always escalate to human (stripe_payments, delete_transaction, approve_payment)
- L4 — reserved, never autonomous

**Self-dealing rule:** Any tool that moves money OUT or cancels a transaction the agent itself initiated → L3. Flagged with ⚠ SELF-DEALING DETECTED.

### NemoClawRouter (`custodian/inference/router.py`)
Tries inference endpoints in priority order with fallback.

**Endpoint order:**
1. OpenRouter (`openrouter.ai`) — primary, model: `nvidia/nemotron-3-super-120b-a12b:free`
2. NVIDIA NIM (`integrate.api.nvidia.com`) — secondary

**Key settings:**
- `max_tokens: 12000` — Nemotron reasons for ~5k tokens before outputting JSON, needs headroom
- `timeout: 120s` — generation takes ~30-90 seconds
- `User-Agent: custodian/1.0` — required or Cloudflare blocks the request

### GovernedReceipt (`custodian/cli/cmd_generate_report.py`)
SHA-256 fingerprints all 4 output files and produces a `delivery-receipt.json`. The fingerprint covers: receipt_id + band + earn_amount + verdict + output_hash. `receipt.verify() → True` confirms nothing was tampered with after generation.

### Email Delivery (`custodian/cli/cmd_send_report.py`)
Sends the 4-file package via Resend API. From: `custodian@getcustodian.xyz` (domain verified). Requires `User-Agent` header or Cloudflare blocks the request.

### Demo Cycle (`custodian/cli/cmd_earn_and_buy.py`)
Orchestrates all 4 steps. Entry point for the camera demo.

---

## Files Delivered to Customer

| File | Contents |
|------|----------|
| `policy.yaml` | Band assignments for every tool in the customer's stack |
| `threat-model.md` | Combination attack scenarios (not single-tool risks) |
| `audit-report.md` | VERIFIED / CONTRADICTED / UNVERIFIABLE verdicts on safety claims |
| `delivery-receipt.json` | SHA-256 fingerprint of all 3 files above |

---

## Secrets

| File | Key | Used for |
|------|-----|---------|
| `secrets/stripe.env` | `STRIPE_SECRET_KEY` | Creating Stripe PaymentIntents |
| `secrets/openrouter.env` | `OPENROUTER_API_KEY` | Nemotron inference via OpenRouter |
| `secrets/resend.env` | `RESEND_API_KEY` | Email delivery via Resend |

**Stripe key:** `rk_live_...` — restricted key, PaymentIntents:Write only. Cannot charge cards, cannot refund, cannot access customer data.

**OpenRouter key:** Free tier. `nvidia/nemotron-3-super-120b-a12b:free` — logs prompts/outputs per NVIDIA free tier policy. Do not send sensitive customer data.

**Resend key:** Free tier, 3,000 emails/month. Domain `getcustodian.xyz` verified.

---

## How to Run

### Prerequisites
```bash
cd /mnt/homes/galileo/argo/Development/hermes-hackathon-2026
pip install -e .
```

### Demo cycle (camera take)
```bash
bash process-orders.sh
```

### Standalone report generation (no Stripe)
```bash
export OPENROUTER_API_KEY=...
python3 -m custodian.cli.main generate-report --out ./delivery/
```

### Run tests
```bash
cd /mnt/homes/galileo/argo/Development/hermes-hackathon-2026
pytest tests/
```

---

## How to Maintain

### Rotate OpenRouter key
1. Go to openrouter.ai → Keys → Create new
2. Update `secrets/openrouter.env`
3. Old key can be revoked immediately

### Rotate Resend key
1. Go to resend.com → API Keys → Create
2. Update `secrets/resend.env`

### Rotate Stripe key
1. Go to dashboard.stripe.com → Developers → API Keys → Restricted keys
2. Create new with PaymentIntents:Write only
3. Update `secrets/stripe.env`

### Change the customer email
Edit `demo.sh` / `process-orders.sh`:
```bash
export CUSTODIAN_DEMO_EMAIL=newcustomer@email.com
```

### Change the inference model
Edit `custodian/inference/router.py`:
```python
OPENROUTER_FALLBACK_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
```
Any OpenRouter model ID works here.

---

## How to Delete

### Delete a specific delivery
```bash
rm -rf delivery/<pi_id>/
```

### Delete all test deliveries
```bash
rm -rf delivery/
```

### Revoke all API access
1. Revoke Stripe restricted key in Stripe dashboard
2. Revoke OpenRouter key at openrouter.ai
3. Revoke Resend key at resend.com

---

## How to Replicate (deploy to production)

To make this a real product:

1. **Real customer checkout** — Stripe payment link or embedded checkout on getcustodian.xyz. Customer fills in their tool list during checkout via custom fields.
2. **Webhook** — Stripe webhook fires on `payment_intent.succeeded` → triggers `process-orders.sh` automatically
3. **Customer inputs from Stripe** — Pass agent_tools, spend_categories, monthly_budget as Stripe checkout custom fields → read from PI metadata
4. **Deploy the Flask app** — `rein.argobox.com` (Cloudflare Pages project `rein-custodian`) or a VPS
5. **Persistent delivery storage** — Move `delivery/` off local disk to S3 or similar
6. **Rate limiting** — One report per payment, keyed on PI ID

---

## How to Improve

### Short term
- Wire Stripe webhook so the cycle triggers automatically on real payment
- Pull customer name and tool list from Stripe checkout custom fields
- Add a web UI to show the customer their report online (not just email)

### Medium term
- Support multiple AI models (let customer choose GPT-4, Claude, Nemotron)
- Add a re-generation endpoint if the customer isn't happy with the report
- Persist receipts to a database so customers can verify later

### Long term
- Expand the kernel to govern real production agent stacks, not just generate reports about them
- Build an API so developers can integrate the kernel into their own agents
- XPRIZE submission — kernel as a standard safety layer for autonomous AI agents

---

## Known Limitations

1. Nemotron free tier logs all prompts/outputs — not suitable for sensitive customer data
2. `process-orders.sh` creates a new Stripe PI on every run — not triggered by real customer payment yet
3. Report quality depends on Nemotron — chain-of-thought reasoning model, occasionally produces inconsistent JSON requiring the multi-strategy parser
4. Email from `custodian@getcustodian.xyz` may land in spam for some providers
5. Local delivery folder (`delivery/`) is not backed up — ephemeral on reboot if on a temp filesystem
6. The kernel bands are hardcoded for the demo — a real product would let customers customize their policy
