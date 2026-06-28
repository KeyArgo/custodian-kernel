# OpenCode Task: Implement Financial + AI Tools

## Context

You are implementing real execute scripts for Custodian-governed financial and AI tools.
The repo is at the current working directory.

## The execute.py contract

- Accept args via `argparse`, print ONE JSON line to stdout, exit 0/1
- Missing credentials → stub response (exit 0, ok:false, stub:true)
- All exceptions caught

## Stripe Tools (test mode — use STRIPE_SECRET_KEY env var)

All Stripe calls use `requests` with `auth=(STRIPE_SECRET_KEY, "")` to `https://api.stripe.com/v1/`.

### `skills/stripe/stripe-balance/scripts/execute.py`

Args: none
```python
r = requests.get("https://api.stripe.com/v1/balance", auth=(key, ""))
data = r.json()
```
Return: `{"ok": true, "tool": "stripe-balance", "available": data["available"], "pending": data["pending"]}`

### `skills/stripe/stripe-customer-lookup/scripts/execute.py`

Args: `--email` OR `--id`

If --id: `GET /v1/customers/{id}`
If --email: `GET /v1/customers?email={email}&limit=1`
Return: `{"ok": true, "tool": "stripe-customer-lookup", "customer": {...}}`

### `skills/stripe/stripe-subscription-create/scripts/execute.py`

Args: `--customer-id`, `--price-id`, `--trial-days` (optional)

```python
data = {"customer": customer_id, "items": [{"price": price_id}]}
if trial_days: data["trial_period_days"] = trial_days
r = requests.post("https://api.stripe.com/v1/subscriptions", auth=(key, ""), data=data)
```
Return: `{"ok": true, "tool": "stripe-subscription-create", "subscription_id": ..., "status": ...}`

### `skills/stripe/stripe-subscription-cancel/scripts/execute.py`

Args: `--subscription-id`, `--at-period-end` (flag, default true)

```python
r = requests.delete(f"https://api.stripe.com/v1/subscriptions/{sub_id}",
    auth=(key, ""), data={"cancel_at_period_end": str(at_period_end).lower()})
```

### `skills/stripe/stripe-invoice-send/scripts/execute.py`

Args: `--invoice-id` OR create a new invoice for `--customer-id`

If --customer-id (no invoice-id):
1. POST /v1/invoices {"customer": customer_id}
2. POST /v1/invoices/{id}/finalize
3. POST /v1/invoices/{id}/send

Return: `{"ok": true, "tool": "stripe-invoice-send", "invoice_id": ..., "hosted_invoice_url": ...}`

### `skills/stripe/stripe-payout/scripts/execute.py`

Args: `--amount` (cents), `--currency` (default usd), `--description`

L4 tool — always requires human approval before executing. The stub is fine here since this is
intentionally restricted. Implement as: print a dry-run description and return:
`{"ok": false, "tool": "stripe-payout", "requires_approval": true, "amount_cents": amount, "description": description}`

(Real payout requires explicit operator approval via `custodian approve` — don't execute autonomously)

## NVIDIA NIM Tools

NVIDIA_API_KEY env var required. Base URL: `https://integrate.api.nvidia.com/v1`

### `skills/nvidia/nim-model-list/scripts/execute.py`

Args: none
```python
r = requests.get("https://integrate.api.nvidia.com/v1/models",
    headers={"Authorization": f"Bearer {api_key}"})
models = [m["id"] for m in r.json().get("data", [])]
```
Return: `{"ok": true, "tool": "nim-model-list", "models": models, "count": len(models)}`

### `skills/nvidia/nim-job-submit/scripts/execute.py`

Args: `--model` (default "meta/llama-3.1-8b-instruct"), `--prompt`, `--max-tokens` (default 256)

```python
payload = {
    "model": model,
    "messages": [{"role": "user", "content": prompt}],
    "max_tokens": max_tokens,
}
r = requests.post("https://integrate.api.nvidia.com/v1/chat/completions",
    headers={"Authorization": f"Bearer {api_key}"},
    json=payload)
result = r.json()
content = result["choices"][0]["message"]["content"]
```
Return: `{"ok": true, "tool": "nim-job-submit", "model": model, "output": content, "usage": result.get("usage")}`

### `skills/nvidia/nim-job-status/scripts/execute.py`

Args: `--job-id`

NIM's `/chat/completions` is synchronous — there's no async job ID unless using async endpoints.
Return: `{"ok": true, "tool": "nim-job-status", "note": "NIM chat/completions is synchronous; use nim-job-submit for results directly", "job_id": job_id}`

### `skills/nvidia/openai-complete/scripts/execute.py`

Args: `--model` (default "gpt-3.5-turbo"), `--prompt`, `--max-tokens` (default 256)

Required: OPENAI_API_KEY env var
Standard OpenAI chat completions endpoint.
Return: `{"ok": true, "tool": "openai-complete", "output": content, "model": model}`

### `skills/nvidia/huggingface-infer/scripts/execute.py`

Args: `--model` (HF model ID), `--inputs`

Required: HUGGINGFACE_API_KEY env var
```python
r = requests.post(f"https://api-inference.huggingface.co/models/{model}",
    headers={"Authorization": f"Bearer {api_key}"},
    json={"inputs": inputs})
```
Return: `{"ok": true, "tool": "huggingface-infer", "model": model, "output": r.json()}`

## Modal Tools

Required: `modal` CLI installed and authenticated (MODAL_TOKEN_ID + MODAL_TOKEN_SECRET env vars)

### `skills/modal/modal-function-list/scripts/execute.py`

```python
r = subprocess.run(["modal", "app", "list", "--json"], capture_output=True, text=True, timeout=30)
```
Return: `{"ok": r.returncode == 0, "tool": "modal-function-list", "output": r.stdout}`

### `skills/modal/modal-invoke/scripts/execute.py`

Args: `--app`, `--function`, `--args` (JSON string)

```python
r = subprocess.run(["modal", "run", f"{app}::{function}"], ...)
```

### `skills/modal/modal-deploy/scripts/execute.py`

Args: `--file` (path to .py)

```python
r = subprocess.run(["modal", "deploy", file_path], ...)
```

## GitHub Tools (needs GITHUB_TOKEN)

### `skills/github/github-issue-create/scripts/execute.py`

Args: `--repo` (owner/repo), `--title`, `--body`, `--labels` (comma-sep, optional)

```python
r = requests.post(f"https://api.github.com/repos/{repo}/issues",
    headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    json={"title": title, "body": body, "labels": labels_list})
```
Return: `{"ok": true, "tool": "github-issue-create", "issue_number": n, "url": url}`

### `skills/github/github-issue-list/scripts/execute.py`

Args: `--repo`, `--state` (open/closed/all, default open), `--limit` (default 10)

### `skills/github/github-pr-list/scripts/execute.py`

Args: `--repo`, `--state` (open/closed/all, default open), `--limit` (default 10)

### `skills/github/github-comment/scripts/execute.py`

Args: `--repo`, `--issue` (number), `--body`

```python
r = requests.post(f"https://api.github.com/repos/{repo}/issues/{issue}/comments", ...)
```

### `skills/github/github-repo-list/scripts/execute.py`

Args: `--user` (or GITHUB_USER env var), `--limit` (default 20)

GET /users/{user}/repos?per_page={limit}

### `skills/github/github-file-read/scripts/execute.py`

Args: `--repo`, `--path`, `--ref` (branch/commit, default main)

GET /repos/{repo}/contents/{path}?ref={ref}
Decode base64 content from response.

## After implementing, test with:

```bash
# NVIDIA (free tier should work with your API key)
python3 skills/nvidia/nim-model-list/scripts/execute.py
python3 skills/nvidia/nim-job-submit/scripts/execute.py --model "meta/llama-3.1-8b-instruct" --prompt "Say hello in one word"

# Web tools (no keys needed)
python3 skills/web/http-get/scripts/execute.py --url https://httpbin.org/get

# GitHub (no key needed for public repos)
python3 skills/github/github-file-read/scripts/execute.py --repo octocat/Hello-World --path README
```
