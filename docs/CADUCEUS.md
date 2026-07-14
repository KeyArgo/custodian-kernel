# Caduceus — the credential broker

Caduceus is a **separate package** from the Custodian kernel. Custodian
decides whether an *action* is allowed; Caduceus decides whether a
*credential* may be materialized for that action — and materializes it so
the agent process never observes the value.

Think password manager + `.env` manager for agents, where the agent gets
a *reference*, never the secret.

## The contract

- Secrets live in one AES-256-GCM vault (scrypt-derived key). Names,
  values, metadata, and grants are all inside the ciphertext — nothing,
  not even the inventory, is readable at rest.
- The agent only ever holds a `SecretRef` — `caduceus://stripe_sk` — which
  is safe to log, print, or put in model context.
- Resolution happens at **egress**: Caduceus injects real values into a
  subprocess environment (or a NemoClaw sandbox exec) at the last moment,
  gated by an explicit grant.
- Every resolve/deny/grant is written to a hash-chained, HMAC-signed
  audit log. Editing or truncating it breaks the chain.

## Humans manage it like a password manager

```bash
caduceus init                                   # create the vault
caduceus add stripe_sk --profile prod --env-var STRIPE_SECRET_KEY
caduceus import-env ./.env --profile dev        # bulk import, then shred the file
caduceus list                                   # names + metadata, never values
caduceus show stripe_sk                          # one entry's metadata
caduceus edit stripe_sk --rotate-value           # replace the value
caduceus rm old_key
caduceus rotate-master                           # re-encrypt under a new passphrase
```

No `caduceus` command ever prints a secret value — not `list`, not `show`,
not errors. The only way a value leaves the vault is egress into a child
process you launch.

## Agents get one verb, through the broker

```bash
# grant: exactly who may resolve what, up to which band, optionally expiring
caduceus grant 'stripe*' --to skill:stripe-spend --max-band L2 --ttl 3600
caduceus grants                                  # list active grants
caduceus revoke 'stripe*' --to skill:stripe-spend

# egress: run a command with secrets injected into ITS environment
caduceus exec --with stripe_sk=STRIPE_SECRET_KEY -- python bill.py
caduceus exec --profile prod -- python agent.py  # inject a whole profile

# audit
caduceus audit                                   # recent decisions
caduceus audit verify                            # walk the hash chain
```

Deny-by-default: with no matching grant, resolution fails and the denial
is audited. Requesters are exact identities (`skill:…`, `sandbox:…`,
`adapter:…`, `user:cli`) — wildcards are allowed only on the ref side, so
you always name precisely *who* gets a secret.

## Programmatic use (the broker)

```python
from caduceus.vault import Vault
from caduceus.broker import Broker

vault = Vault.open(passphrase=...)
broker = Broker(vault)
broker.grant("stripe_sk", "skill:stripe-spend", max_band="L2")

# Run a governed subprocess with the secret in its env — never in argv,
# never in this process:
proc = broker.spawn(
    ["python", "charge.py"],
    refs={"STRIPE_SECRET_KEY": "caduceus://stripe_sk"},
    requester="skill:stripe-spend", band="L2",
)
```

## Optional: signed receipts

`caduceus.receipts.sign_receipt(receipt, vault)` co-signs a kernel
`GovernedReceipt` with an HMAC keyed by the vault, adding *authenticity*
(not just integrity) for sites that need non-repudiation. See
`docs/SECURITY-HARDENING.md` finding F2.

## Configuration

| Env var | Meaning |
|---|---|
| `CADUCEUS_HOME` | vault directory (default `~/.caduceus`) |
| `CADUCEUS_PASSPHRASE` | passphrase for non-interactive use (CI, services) |
| `CADUCEUS_KEYFILE` | path to a 32-byte keyfile instead of a passphrase |

Install the crypto dependency with `pip install custodian-kernel[caduceus]`.
