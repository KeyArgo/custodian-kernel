# Getting Started

This walkthrough takes approximately 10 minutes. It uses only commands
that exist in the Custodian CLI. Before starting, verify the test suite
passes:

```bash
cd /tmp/hermes-hackathon-2026
pip install -e ".[dev]" 2>&1 | tail -3
pytest tests/ -v --tb=short 2>&1 | tail -5
```

You should see `117 passed, 1 skipped`.

## Step 1: Create a workspace

```bash
custodian init --dir /tmp/custodian-demo
```

You will see:

```
created /tmp/custodian-demo/policy.yaml
created /tmp/custodian-demo/state/
created /tmp/custodian-demo/secrets/
created /tmp/custodian-demo/secrets/.gitkeep
created /tmp/custodian-demo/secrets/README.md

Custodian workspace initialized. Edit policy.yaml to configure authority bands.
```

## Step 2: Inspect the generated policy

```bash
cat /tmp/custodian-demo/policy.yaml
```

This is the default policy with five bands (L0–L4). The default band is
L2, which allows autonomous spend up to $2.00 per action and $10.00 per
session. Above those caps, escalation requires Twilio Verify approval.

Validate the policy:

```bash
custodian validate /tmp/custodian-demo/policy.yaml
```

You will see:

```
Policy: /tmp/custodian-demo/policy.yaml
  Version: 1.0
  Default band: L2
  Bands (5):
    L0: max $0.00, autonomous
    L1: max $0.50, autonomous
    L2: max $2.00, autonomous
    L3: max $50.00, requires approval, approval: twilio_verify
    L4: max unlimited, requires approval, approval: twilio_verify
  Rules: none
  Escalation: timeout=600s, on_timeout=deny
```

## Step 3: Autonomous request (under the cap)

```bash
custodian request --amount 1.00 --description "API credits" --state-dir /tmp/custodian-demo/state --policy /tmp/custodian-demo/policy.yaml
```

You will see:

```
warning: no authority state found, using defaults (L2, $2.00 cap, $10.00 session)
Verdict: AUTONOMOUS
Reason: $1.00 within band L2 (cap $2.00, remaining $10.00)
Band: L2

(No real payment was executed — this CLI exposes the decision only.)
```

The first request warns that no state exists yet and uses defaults. The
CLI only returns decisions — it does not execute real payments.

## Step 4: Request that requires escalation (over the cap)

```bash
custodian request --amount 50.00 --description "Server upgrade" --state-dir /tmp/custodian-demo/state --policy /tmp/custodian-demo/policy.yaml
```

You will see:

```
warning: no authority state found, using defaults (L2, $2.00 cap, $10.00 session)
Verdict: ESCALATION_REQUIRED
Reason: $50.00 exceeds band L2 max_spend $2.00; $50.00 exceeds remaining session budget $10.00
Band: L2
Pending approval saved.
warning: cannot send challenge — Twilio operator phone not configured. Set CUSTODIAN_OPERATOR_PHONE env var or add TWILIO_OPERATOR_PHONE=<number> to secrets/twilio.env
Pending approval was saved. Use 'custodian approve <CODE> --approved-by <NAME>' if you have a code.
```

This is expected — without real Twilio credentials, the challenge cannot
be sent. The pending approval is saved to the database, and you can see
the warning about missing Twilio configuration. This is not a bug; it is
the correct behavior when secrets are not configured.

If you had Twilio credentials configured, the operator would receive an
SMS code and could approve with:

```bash
custodian approve 123456 --approved-by "Alice" --state-dir /tmp/custodian-demo/state
```

## Step 5: Check authority state

```bash
custodian status --state-dir /tmp/custodian-demo/state
```

You will see:

```
No authority state initialized. Defaults would be:
  Band: L2
  Per-action cap: $2.00
  Session cap: $10.00
  Spent this session: $0.00
  Remaining: $10.00
```

The state database exists but no authority state has been persisted yet
(the CLI only returns decisions, it does not execute real payments). The
status command shows the defaults that would apply.

## Step 6: View the audit log

```bash
custodian audit --state-dir /tmp/custodian-demo/state
```

You will see:

```
No audit entries found.
```

No audit entries exist because the CLI only prints decisions — it does not
log them automatically. Real audit entries are created when approvals are
processed or denied through the privileged path.

## Step 7: Deny the pending approval (cleanup)

```bash
custodian deny --denied-by "Alice" --state-dir /tmp/custodian-demo/state
```

You will see:

```
Denied: $50.00 for 'Server upgrade' by Alice
```

This clears the pending approval and writes a `denied` audit entry.

Now confirm the audit log:

```bash
custodian audit --state-dir /tmp/custodian-demo/state
```

You will see:

```
[2026-...] denied: $50.00 'Server upgrade' band=L2 (denied by Alice)
```

## Step 8: Request with a context flag

This demonstrates rule matching with the `--context` flag:

```bash
custodian request --amount 1.00 --description "Critical server provision" --skill provision-server --context critical=true --state-dir /tmp/custodian-demo/state --policy /tmp/custodian-demo/policy.yaml
```

You will see the autonomous verdict (the default policy has no rules, so
`--skill` and `--context` have no effect without rules). If you add a rule
like the one in the policy language docs, this request would be routed to
L4 (always requires approval).

## Step 9: The kill switch

An operator-only emergency stop that overrides every band and cap, with no
exceptions:

```bash
custodian kill --by "Alice" --reason "testing" --state-dir /tmp/custodian-demo/state
```

You will see:

```
KILL SWITCH ENGAGED by Alice. Every request will be denied until 'custodian resume' is run.
Reason: testing
```

Now the same request that would normally be autonomous is denied:

```bash
custodian request --amount 1.00 --description "test" --state-dir /tmp/custodian-demo/state --policy /tmp/custodian-demo/policy.yaml
```

```
DENIED: kill switch is engaged (by Alice, reason: testing).
Run 'custodian resume --by <name>' to release it.
```

(Exit code 3.) Release it:

```bash
custodian resume --by "Alice" --state-dir /tmp/custodian-demo/state
```

```
Kill switch released by Alice. Normal decisions will resume.
```

This is the same mechanism wired into the real, live, authoritative
`spend.py` script used elsewhere in this project — not a separate demo path.

## Cleanup

```bash
rm -rf /tmp/custodian-demo
```

## Summary of commands used

| Command | What it does |
|---|---|
| `custodian init --dir DIR` | Scaffolds a workspace with policy.yaml, state/, secrets/ |
| `custodian validate FILE` | Validates a policy file |
| `custodian request --amount X --description "..."` | Submits a spend request |
| `custodian approve CODE --approved-by NAME` | Approves a pending escalation |
| `custodian deny --denied-by NAME` | Denies a pending escalation |
| `custodian status` | Shows current authority state |
| `custodian audit` | Shows audit log entries |
| `custodian kill --by NAME` | Engages the kill switch -- denies everything until released |
| `custodian resume --by NAME` | Releases the kill switch |
