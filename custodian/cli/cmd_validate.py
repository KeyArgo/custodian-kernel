from __future__ import annotations

import sys
from pathlib import Path

from custodian.exceptions import PolicyNotFoundError, PolicyValidationError
from custodian.policy.loader import load_policy


def run(args) -> None:
    path = Path(args.policy_path).resolve()
    try:
        policy = load_policy(path)
    except FileNotFoundError:
        print(f"error: policy file not found: {path}", file=sys.stderr)
        raise SystemExit(1)
    except PolicyNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(1)
    except PolicyValidationError as e:
        print(f"error: invalid policy: {e}", file=sys.stderr)
        raise SystemExit(1)
    except Exception as e:
        print(f"error: failed to load policy: {e}", file=sys.stderr)
        raise SystemExit(1)

    print(f"Policy: {path}")
    print(f"  Version: {policy.version}")
    print(f"  Default band: {policy.default_band.value}")
    print(f"  Bands ({len(policy.bands)}):")
    for b in sorted(policy.bands, key=lambda x: x.value):
        cfg = policy.bands[b]
        max_s = f"${cfg.max_spend:.2f}" if cfg.max_spend is not None else "unlimited"
        approval = f", approval: {cfg.approval_backend}" if cfg.requires_approval else ""
        print(f"    {b.value}: max {max_s}, {'requires approval' if cfg.requires_approval else 'autonomous'}{approval}")
    if policy.rules:
        print(f"  Rules ({len(policy.rules)}):")
        for r in policy.rules:
            cond_parts = []
            if r.match.skill is not None:
                cond_parts.append(f"skill={r.match.skill}")
            if r.match.spend_estimate_gt is not None:
                cond_parts.append(f"amount>${r.match.spend_estimate_gt:.2f}")
            if r.match.context_flag is not None:
                cond_parts.append(f"context.{r.match.context_flag}")
            cond_str = ", ".join(cond_parts) if cond_parts else "always"
            print(f"    [{r.order}] if {cond_str} -> {r.assign_band.value}")
    else:
        print("  Rules: none")
    print(f"  Escalation: timeout={policy.escalation.timeout_seconds}s, on_timeout={policy.escalation.on_timeout}")
