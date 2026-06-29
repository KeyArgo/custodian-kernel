from __future__ import annotations

import os
import sys
from pathlib import Path

from custodian.backends.twilio_verify import TwilioVerifyBackend
from custodian.exceptions import BackendConfigurationError, PolicyNotFoundError, PolicyValidationError
from custodian.policy.evaluator import decide
from custodian.policy.loader import load_policy
from custodian.storage.sqlite import SqliteStorage
from custodian.types import AuthorityState, PendingApproval, SpendRequest, Verdict


def _twilio_backend(state_dir: Path) -> TwilioVerifyBackend:
    secret_file = state_dir.parent / "secrets" / "twilio.env"
    if not secret_file.exists():
        secret_file = Path("./secrets/twilio.env").resolve()

    operator_phone = os.environ.get("CUSTODIAN_OPERATOR_PHONE")
    if not operator_phone and secret_file.exists():
        for line in secret_file.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                ks = k.strip()
                if ks in ("TWILIO_OPERATOR_PHONE", "TO_PHONE"):
                    operator_phone = v.strip()

    if not operator_phone:
        raise BackendConfigurationError(
            "Twilio operator phone not configured. "
            "Set CUSTODIAN_OPERATOR_PHONE env var or add "
            "TWILIO_OPERATOR_PHONE=<number> to secrets/twilio.env"
        )
    return TwilioVerifyBackend(secret_file=secret_file, operator_phone=operator_phone)


def run(args) -> None:
    state_dir = Path(args.state_dir).resolve()
    policy_path = Path(args.policy).resolve()

    # If the specified policy doesn't exist, look in the workspace directory
    if not policy_path.exists():
        for candidate in [state_dir / "policy.yaml", state_dir.parent / "policy.yaml"]:
            if candidate.exists():
                policy_path = candidate
                break

    try:
        policy = load_policy(policy_path)
    except PolicyNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(1)
    except PolicyValidationError as e:
        print(f"error: invalid policy: {e}", file=sys.stderr)
        raise SystemExit(1)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(1)

    db_path = state_dir / "custodian.db"
    try:
        storage = SqliteStorage(db_path)
        state = storage.load_authority_state()
    except Exception as e:
        print(f"error: failed to load state: {e}", file=sys.stderr)
        raise SystemExit(1)

    if state is None:
        state = AuthorityState(band=policy.default_band, per_action_cap=2.0, session_cap=10.0, spent_this_session=0.0)
        print("warning: no authority state found, using defaults (L2, $2.00 cap, $10.00 session)")

    if args.amount <= 0:
        print("error: amount must be positive", file=sys.stderr)
        raise SystemExit(1)

    kill_state = storage.get_kill_switch()
    if kill_state.killed:
        print(f"DENIED: kill switch is engaged (by {kill_state.by or 'operator'}"
              f"{f', reason: ' + kill_state.reason if kill_state.reason else ''}).")
        print("Run 'custodian resume --by <name>' to release it.")
        raise SystemExit(3)

    context: dict = {}
    for raw in getattr(args, "context", []) or []:
        if "=" not in raw:
            print(f"error: --context expects FLAG=true|false, got '{raw}'", file=sys.stderr)
            raise SystemExit(1)
        key, _, value = raw.partition("=")
        context[key.strip()] = value.strip().lower() in ("true", "1", "yes")

    request = SpendRequest(amount=args.amount, description=args.description)
    decision = decide(request, state, policy, skill=args.skill, context=context)

    if decision.verdict == Verdict.AUTONOMOUS:
        print(f"Verdict: AUTONOMOUS")
        print(f"Reason: {decision.reason}")
        print(f"Band: {decision.band.value}")
        print("\n(No real payment was executed — this CLI exposes the decision only.)")

    elif decision.verdict == Verdict.ESCALATION_REQUIRED:
        print(f"Verdict: ESCALATION_REQUIRED")
        print(f"Reason: {decision.reason}")
        print(f"Band: {decision.band.value}")

        band_cfg = policy.bands.get(decision.band)
        backend_name = band_cfg.approval_backend if band_cfg else None

        pending = PendingApproval(amount=args.amount, description=args.description, reason=decision.reason)
        try:
            storage.set_pending_approval(pending)
            print("Pending approval saved.")
        except Exception as e:
            print(f"error: failed to save pending approval: {e}", file=sys.stderr)
            raise SystemExit(1)

        if backend_name == "twilio_verify":
            try:
                backend = _twilio_backend(state_dir)
                backend.send_challenge(amount=args.amount, description=args.description)
                print("Approval challenge sent to operator via Twilio Verify.")
                print("Use 'custodian approve <CODE> --approved-by <NAME>' to approve.")
            except BackendConfigurationError as e:
                print(f"warning: cannot send challenge — {e}")
                print("Pending approval was saved. Use 'custodian approve <CODE> --approved-by <NAME>' if you have a code.")
            except Exception as e:
                print(f"warning: failed to send challenge — {e}")
                print("Pending approval was saved. Use 'custodian approve <CODE> --approved-by <NAME>' if you have a code.")
        elif backend_name and backend_name != "none":
            print(f"warning: approval backend '{backend_name}' is not wired in this CLI — challenge not sent.")
        else:
            print("No approval backend configured for this band — challenge not sent.")

    elif decision.verdict == Verdict.DENIED:
        print(f"Verdict: DENIED")
        print(f"Reason: {decision.reason}")
        print(f"Band: {decision.band.value}")
