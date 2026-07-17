# Paladin — the credential broker

Paladin is a **separate package** from the Custodian kernel. Custodian
decides whether an *action* is allowed; Paladin decides whether a
*credential* may be materialized for that action — and materializes it so
the agent process never observes the value.

Think password manager + `.env` manager for agents, where the agent gets
a *reference*, never the secret.

## The contract

- Secrets live in one AES-256-GCM vault (scrypt-derived key). Names,
  values, metadata, and grants are all inside the ciphertext — nothing,
  not even the inventory, is readable at rest.
- The agent only ever holds a `SecretRef` — `paladin://stripe_sk` — which
  is safe to log, print, or put in model context.
- Resolution happens at **egress**: Paladin injects real values into a
  subprocess environment (or a NemoClaw sandbox exec) at the last moment,
  gated by an explicit grant.
- Every resolve/deny/grant is written to a hash-chained, HMAC-signed
  audit log. Editing or truncating it breaks the chain.

## Humans manage it like a password manager

```bash
paladin init                                   # create the vault
paladin add stripe_sk --profile prod --env-var STRIPE_SECRET_KEY
paladin import-env ./.env --profile dev        # bulk import, then shred the file
paladin list                                   # names + metadata, never values
paladin show stripe_sk                          # one entry's metadata
paladin edit stripe_sk --rotate-value           # replace the value
paladin rm old_key
paladin rotate-master                           # re-encrypt under a new passphrase
```

No `paladin` command ever prints a secret value — not `list`, not `show`,
not errors. The only way a value leaves the vault is egress into a child
process you launch.

## Backup & moving machines

```bash
paladin backup                                  # → ~/paladin-backups/paladin-backup-<time>.zip
paladin backup /mnt/usb/                        # or anywhere you point it
paladin restore paladin-backup-20260716.zip     # here, or on a new machine
```

One backup file carries the **encrypted vault** and the **HMAC-chained audit
trail** — after a restore on a new machine, `paladin audit verify` still
passes. The guarantees, in order of what matters:

- **The backup is proven restorable at creation.** `backup` opens the vault
  with your passphrase first; if it can't, no backup is written. You will
  never discover a dead backup during disaster recovery.
- **Ciphertext in, ciphertext out.** The vault bytes are copied under the
  same write lock `save()` uses and never decrypted into the archive. A
  stolen backup reveals exactly what a stolen vault reveals: its size.
- **Your keys are never inside it.** Keyfiles are deliberately excluded —
  store the backup and the passphrase/keyfile in different places.
- **Restore can't destroy data.** It verifies the backup decrypts *before*
  touching anything, refuses to overwrite without `--force`, and even then
  saves the current vault and audit log to `*.pre-restore` first. It also
  accepts a bare `vault.paladin` file, so a partial salvage still restores.
- **Rotation footgun handled:** `rotate-master` reminds you that backups
  made before a rotation need the *old* passphrase — and to take a fresh one.

## Agents get one verb, through the broker

```bash
# grant: exactly who may resolve what, up to which band, optionally expiring
paladin grant 'stripe*' --to skill:stripe-spend --max-band L2 --ttl 3600
paladin grants                                  # list active grants
paladin revoke 'stripe*' --to skill:stripe-spend

# egress: run a command with secrets injected into ITS environment
paladin exec --with stripe_sk=STRIPE_SECRET_KEY -- python bill.py
paladin exec --profile prod -- python agent.py  # inject a whole profile

# audit
paladin audit                                   # recent decisions
paladin audit verify                            # walk the hash chain
```

Deny-by-default: with no matching grant, resolution fails and the denial
is audited. Requesters are exact identities (`skill:…`, `sandbox:…`,
`adapter:…`, `user:cli`) — wildcards are allowed only on the ref side, so
you always name precisely *who* gets a secret.

## Programmatic use (the broker)

```python
from paladin.vault import Vault
from paladin.broker import Broker

vault = Vault.open(passphrase=...)
broker = Broker(vault)
broker.grant("stripe_sk", "skill:stripe-spend", max_band="L2")

# Run a governed subprocess with the secret in its env — never in argv,
# never in this process:
proc = broker.spawn(
    ["python", "charge.py"],
    refs={"STRIPE_SECRET_KEY": "paladin://stripe_sk"},
    requester="skill:stripe-spend", band="L2",
)
```

## Optional: signed receipts

`paladin.receipts.sign_receipt(receipt, vault)` co-signs a kernel
`GovernedReceipt` with an HMAC keyed by the vault, adding *authenticity*
(not just integrity) for sites that need non-repudiation. See
`docs/SECURITY-HARDENING.md` finding F2.

## Configuration

| Env var | Meaning |
|---|---|
| `PALADIN_HOME` | vault directory (default `~/.paladin`) |
| `PALADIN_PASSPHRASE` | passphrase for non-interactive use (CI, services) |
| `PALADIN_KEYFILE` | path to a 32-byte keyfile instead of a passphrase |

Install the crypto dependency with `pip install custodian-kernel[paladin]`.
