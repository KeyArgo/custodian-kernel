# Guard adapters

## Package boundaries — why "the adapter," not an import

Three packages ship in this repo, and the dependency arrow only ever
points one way:

```
custodian/  (kernel + adapter framework)  ←──┐
                                              │  talaria/ imports both.
paladin/    (credential broker)           ←──┘  Nothing imports talaria.
```

- **`custodian/` never imports `paladin/` or `talaria/`.** The kernel
  and the built-in adapters are brand-neutral: they know nothing about
  Hermes, and nothing about the broker's Python API.
- **`paladin/` never imports `custodian/` or `talaria/`.** The broker
  is a standalone credential vault — usable with zero AI-agent
  framework installed at all (`pip install custodian-kernel[paladin]`
  and you have `paladin init`/`add`/`exec`, nothing else required).
- **`talaria/` is the only package that imports both.** Wiring a
  specific broker to a specific kernel's adapters for a specific agent
  (Hermes) is talaria's entire job. A future Claude/Codex integration
  package would sit at this same layer — never inside `custodian/` or
  `paladin/` — importing both the same way talaria does.

This isn't just a convention — `tests/test_architecture_boundaries.py`
parses every file in `custodian/` and `paladin/` with `ast` and fails
the suite if either one ever imports the other or `talaria`. Run it
directly any time you want to re-check the boundary yourself:

```bash
pytest tests/test_architecture_boundaries.py -v
```

**How custodian's adapters reference `paladin://` without importing
`paladin` at all** — two ways, both string/config level, never code:

1. **Protocol-string awareness.** `egress-domain-guard` and
   `secret-leak-guard` recognize the literal `paladin://` URI prefix
   with a regex, the same way they'd recognize `https://` — they parse
   a string pattern, not a `SecretRef` object from the `paladin`
   package. `path-fence` uses the same trick to protect the vault's
   home directory (`~/.paladin`) without importing anything to learn
   that path.
2. **Plain-dict configuration, populated by the caller.** `talaria/policy.py`'s
   `build_pipeline()` is the one place that actually imports
   `paladin.vault`, reads `vault.iter_meta()` for each secret's
   `allowed_hosts`, and hands the *result* — an inert
   `{secret_name: [host, ...]}` dict — to `EgressDomainGuard(
   {"ref_hosts": ref_hosts})`. The adapter never sees the vault object,
   never imports `paladin`, and would work identically if some other
   caller populated that same dict from a config file instead.

Guard adapters are pluggable pre/post hooks around every governed action.
The kernel decides *whether* an action is allowed (bands, caps, envelopes,
kill switch). Adapters decide whether an allowed action is *sane* — they
catch what a model does wrong *inside* its authority.

Everything is an adapter. There is no bloated built-in policy engine for
this layer: you enable exactly the risk surface you want, and third
parties ship their own.

## The model

An adapter implements up to three hooks:

- `pre_action(ctx)` → **ALLOW / WARN / TRANSFORM / DENY** before execution.
- `post_action(ctx)` → same, after execution, with `ctx.output` set.
- `handle_action(ctx)` → optionally *answer* the action itself (a
  capability, not a veto) — e.g. the Hermes introspection adapter serves
  `custodian-status` with no subprocess.

A DENY short-circuits the pipeline. TRANSFORMs chain (each adapter sees
the previous one's edits). A crashing adapter becomes a DENY if it
declared `fail_closed`, else a WARN — the pipeline never dies mid-run.

## Built-ins

| Adapter | Category | What it catches |
|---|---|---|
| `spend-sentinel` | money | duplicate spends, spend loops, cap-probing |
| `prompt-injection-guard` | security | instruction-override / exfil / role-hijack payloads in tool args (incl. base64-smuggled) |
| `secret-leak-guard` | security | credentials in args (deny) or output (redact); Paladin-value tripwire |
| `kernel-self-protection` | security | writes to policy, vault, kill switch, adapters, or the skills tree |
| `pii-redactor` | privacy | emails, phones, SSNs, Luhn-checked cards, IPs |
| `context-anchor` | guardrail | tool fences + session budget, enforced regardless of what the model remembers |
| `repetition-breaker` | guardrail | hammering, ping-pong, retry storms |
| `tool-confabulation-guard` | guardrail | calls to tools/args that don't exist (with `did you mean…`) |
| `scope-fence` | guardrail | file/host/arg reach outside the current task scope |
| `path-fence` | security | denylist read/write fence (`~/.ssh`, `*.env`, ...), reads AND writes, including shell-command paths |
| `egress-domain-guard` | security | a host-restricted `paladin://` secret sent to a non-approved destination |

## CLI

```bash
custodian adapters list                        # available + enabled, by category
custodian adapters enable spend-sentinel --config '{"max_per_minute": 4}'
custodian adapters disable pii-redactor
custodian adapters install ./my_guard.py       # local file, SHA-256 pinned
custodian adapters check stripe-spend --args '{"amount": 5}' --band L2
```

Installed local adapters are **hash-pinned**: if the file changes after
install, it refuses to load.

## Writing one

```python
from custodian.adapters.base import Adapter, Verdict

class BusinessHoursGuard(Adapter):
    name = "business-hours"
    category = "guardrail"
    fail_closed = True

    def pre_action(self, ctx):
        import datetime
        if ctx.skill.startswith("stripe-") and datetime.datetime.now().hour < 6:
            return Verdict.deny(self.name, "no payments before 06:00")
        return Verdict.allow(self.name)
```

Ship it as a pip package exposing the `custodian.adapters` entry-point
group, or `custodian adapters install ./business_hours.py` locally.

## In Talaria

Two independent compilers build a pipeline from YAML (see
`docs/TALARIA.md` for which one applies to you):

- `talaria/policy.py`'s `build_pipeline()` compiles `~/.talaria/policy.yaml`
  into the pipeline the Hermes plugin runs on every tool call
  (`talaria hermes install`) — the everyday "keep the agent out of my
  files and secrets" surface.
- `talaria/session_policy.py`'s `build_bridge()` compiles a
  `hermes-session.yaml` into a full `HermesBridge` with kernel spend
  governance (bands, budget, kill switch) layered in — for embedding
  directly, not wired into the plugin path.

Both expose the same `guards:` shape (kernel-grade guards always on,
`pii`/`repetition`/etc. togglable) and all of the above applies to
Hermes automatically with granular per-session control over tools,
files, hosts, spend, and privacy.
