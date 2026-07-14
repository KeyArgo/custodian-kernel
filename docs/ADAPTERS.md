# Guard adapters

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
| `secret-leak-guard` | security | credentials in args (deny) or output (redact); Caduceus-value tripwire |
| `kernel-self-protection` | security | writes to policy, vault, kill switch, adapters, or the skills tree |
| `pii-redactor` | privacy | emails, phones, SSNs, Luhn-checked cards, IPs |
| `context-anchor` | guardrail | tool fences + session budget, enforced regardless of what the model remembers |
| `repetition-breaker` | guardrail | hammering, ping-pong, retry storms |
| `tool-confabulation-guard` | guardrail | calls to tools/args that don't exist (with `did you mean…`) |
| `scope-fence` | guardrail | file/host/arg reach outside the current task scope |

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

## In the Hermes bridge

The bridge builds a pipeline from a single session-policy YAML (see
`docs/HERMES-BRIDGE.md`) and runs it around every skill call, so all of
the above applies to Hermes automatically with granular per-session
control over tools, files, hosts, spend, and privacy.
