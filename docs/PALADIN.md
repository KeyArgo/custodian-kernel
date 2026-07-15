# Paladin — the credential broker

Paladin is a **separate, standalone package** from the Custodian kernel
— zero imports from `custodian/` or `talaria/`, in either direction
(enforced by `tests/test_architecture_boundaries.py`, not just
documented). Custodian decides whether an *action* is allowed; Paladin
decides whether a *credential* may be materialized for that action —
and materializes it so the agent process never observes the value.
`pip install custodian-kernel[paladin]` and you have a working vault
with zero AI-agent framework installed — Custodian's built-in adapters
recognize the `paladin://` URI convention by regex, never by importing
this package (see `docs/ADAPTERS.md`'s "Package boundaries" section for
exactly how that works).

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

## Hardening

- **Key derivation:** scrypt, `N=2**17` (~128MB memory cost, well under
  a second) — bumped from an earlier `2**15` ("interactive-grade," fine
  for a login screen, too weak for a vault meant to resist offline
  brute-force of a stolen file indefinitely). KDF params are stored
  per-vault in the header, so existing vaults keep working with
  whatever `N` they were created with until `rotate-master` runs.
- **In-memory cleanup:** `Vault` is a context manager —
  `with Vault.open(...) as v:` zeroes the master key (stored as a
  `bytearray` specifically so this is possible) and drops entry
  references on exit, shrinking the window plaintext sits in RAM. Not
  a hard guarantee — Python strings are immutable, so a decrypted
  `Entry.value` can only be dereferenced, not zeroed in place — but
  strictly better than relying on GC timing alone.
- **Concurrent writers:** `save()` holds an exclusive `flock` on a
  sibling `.lock` file for the duration of the write, so two `paladin`
  CLI invocations racing serialize instead of one silently clobbering
  the other's write. This protects the write itself, not the full
  open→modify→save lifecycle across two processes.

## Sandboxed egress — the credential never enters the tool process

The `exec` flow above injects secrets into a child's **environment**. That
keeps them out of the *agent*, but the child itself can read its own
`os.environ` — so a prompt-injected tool payload could exfiltrate the
value. `paladin exec --sandbox` closes that gap:

```bash
paladin exec --sandbox --as sandbox:demo --band L1 --with stripe_sk -- python3 tool.py
```

The child runs under `bwrap --unshare-all` — **no network at all**, fresh
namespaces, the vault directory and keyfile masked to empty, and a rebuilt
minimal environment (it can't even inherit your `PALADIN_PASSPHRASE`). Its
only path out is a Unix socket to an in-process Paladin gateway. Inside the
tool you make authenticated calls without ever holding the key:

```python
from paladin.egress_client import Session

s = Session()  # reads the gateway socket + token from the sandbox env
r = s.post(
    "https://api.stripe.com/v1/refunds",
    ref="stripe_sk",
    inject={"header": "Authorization", "format": "Bearer {value}"},
    body="charge=ch_123&amount=500",
)
print(r["status"], r["body"])   # the key was never in this process
```

Paladin resolves the ref host-side (grant-gated + audited), attaches the
credential, makes the call, and hands back only `{status, headers, body}`.
Scope the grant so a leaked descriptor is still useless:

```bash
paladin grant 'stripe*' --to sandbox:demo --max-band L2 \
    --host api.stripe.com --method POST --path-prefix /v1/refunds
```

`--host`/`--method`/`--path-prefix` **narrow** what a resolved secret may
do; they never widen the entry's own `allowed_hosts` ceiling (a request
must satisfy both). `paladin doctor` reports whether the sandbox is
available here — and if it isn't, `--sandbox` **fails closed** rather than
silently falling back to plaintext-env injection.

**Honest scope.** This covers HTTP(S) request-shaped secrets; SSH keys and
DB creds still use `exec` env-injection until per-protocol brokers exist.
It confines the *credential*, not the *data* a call returns — and if an API
echoes the secret in its response, the child sees it coming back (the
secret-leak guard detects that; it doesn't prevent it). The strong "never
in the process" guarantee holds where the sandbox is active (Linux +
unprivileged user namespaces) and, for host confinement, where
`allowed_hosts` is set. See `docs/SECURITY-HARDENING.md` finding F4.

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
