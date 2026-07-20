from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

from custodian.backends.twilio_verify import TwilioVerifyBackend
from custodian.cli.cmd_init import DEFAULT_SESSION_CAP
from custodian.exceptions import BackendConfigurationError, PolicyNotFoundError, PolicyValidationError
from custodian.policy.evaluator import decide
from custodian.policy.loader import load_policy
from custodian.storage.sqlite import SqliteStorage
from custodian.types import AuditEntry, AuthorityState, PendingApproval, SpendRequest, Verdict
from custodian.universal_ledger import LedgerEvent, UniversalLedger


def _ledger_write(ledger: UniversalLedger, **kw) -> None:
    """Never let a ledger write failure block the CLI -- same resilience
    posture the existing storage.append_audit_entry() calls already have
    in this file. The ledger is additive tonight, not yet the only record."""
    try:
        ledger.append(LedgerEvent(**kw))
    except Exception as e:
        print(f"warning: failed to write ledger event: {e}", file=sys.stderr)


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

    state_persisted = state is not None
    if state is None:
        # Derive the cap from the policy rather than hardcoding 2.0: an
        # operator who edits policy.yaml and then runs a request before any
        # state exists would otherwise be governed by a cap their policy never
        # mentions. `custodian init` now writes state up front, so this path is
        # for a workspace that was not scaffolded.
        band = policy.default_band
        cap = policy.bands[band].max_spend
        per_action = DEFAULT_SESSION_CAP if cap is None else float(cap)
        state = AuthorityState(band=band, per_action_cap=per_action,
                               session_cap=DEFAULT_SESSION_CAP, spent_this_session=0.0)
        print(f"warning: no authority state found, using policy defaults "
              f"({band.value}, ${per_action:.2f} cap, ${DEFAULT_SESSION_CAP:.2f} session). "
              f"Run 'custodian init' to create it.")

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

    ledger = UniversalLedger(state_dir / "ledger.db")
    correlation_id = uuid.uuid4().hex
    verdict_name = decision.verdict.value.lower()
    _ledger_write(
        ledger, correlation_id=correlation_id, requester="cli:request",
        provider="custodian", action=args.skill or "cli-request",
        lifecycle_event="proposed", amount=args.amount, currency="USD",
        metadata={"description": args.description[:200]},
    )
    _ledger_write(
        ledger, correlation_id=correlation_id, requester="cli:request",
        provider="custodian", action=args.skill or "cli-request",
        lifecycle_event="decided", verdict=verdict_name,
        band=decision.band.value, amount=args.amount, currency="USD",
        metadata={"reason": decision.reason[:200]},
    )

    if decision.verdict == Verdict.AUTONOMOUS:
        print(f"Verdict: AUTONOMOUS")
        print(f"Reason: {decision.reason}")
        print(f"Band: {decision.band.value}")

        # An AUTONOMOUS verdict grants authority, so it must consume the
        # session budget and land in the audit ledger -- otherwise the session
        # cap never decreases and `custodian confirm <id>` has nothing to find.
        request_id = f"req_{uuid.uuid4().hex[:8]}"
        try:
            storage.append_audit_entry(AuditEntry(
                event="executed", amount=args.amount, description=args.description,
                band=decision.band, payment_intent_id=request_id,
                reason=decision.reason,
            ))
            print(f"Request-ID: {request_id}  (confirm with: custodian confirm {request_id})")
        except Exception as e:
            print(f"warning: failed to write audit entry: {e}", file=sys.stderr)
        _ledger_write(
            ledger, correlation_id=correlation_id, requester="cli:request",
            provider="custodian", action=args.skill or "cli-request",
            lifecycle_event="executed", verdict=verdict_name, band=decision.band.value,
            amount=args.amount, currency="USD", external_id=request_id,
        )

        if state_persisted:
            try:
                storage.record_spend(args.amount)
                spent = state.spent_this_session + args.amount
                print(f"Session spent: ${spent:.2f} of ${state.session_cap:.2f}")
            except Exception as e:
                print(f"warning: failed to record spend: {e}", file=sys.stderr)

        print("\n(No real payment was executed — this CLI exposes the decision only.)")

    elif decision.verdict == Verdict.ESCALATION_REQUIRED:
        print(f"Verdict: ESCALATION_REQUIRED")
        print(f"Reason: {decision.reason}")
        print(f"Band: {decision.band.value}")

        # pending_approval is a single-row table (INSERT OR REPLACE), and the
        # Twilio Verify SMS challenge below carries no reference to which
        # request it's for (a standard "your code is: XXXXXX" template) --
        # so a second escalation landing before the first is resolved used
        # to silently overwrite it. An operator who received a code for a
        # small request, got distracted, and later typed it in had no way
        # to tell -- from the SMS alone -- that `custodian approve` would
        # actually charge whatever the SECOND, unrelated request asked for.
        # Reproduced: escalate $5 "small legit request", then escalate
        # $99999 "drain the account" before approving -- the operator's
        # original code approved the $99999 charge. Found in review. Fail
        # closed instead: refuse a new escalation while one is still
        # outstanding, rather than silently discarding it.
        existing = storage.get_pending_approval()
        if existing is not None:
            ttl = int(os.environ.get("CUSTODIAN_PENDING_TTL_SECONDS", "600"))
            if not existing.is_expired(ttl_seconds=ttl):
                print(
                    f"error: a pending approval is already outstanding "
                    f"(${existing.amount:.2f} for {existing.description!r}) — "
                    f"resolve it first with 'custodian approve <CODE>' or "
                    f"'custodian deny' before requesting another escalation",
                    file=sys.stderr,
                )
                raise SystemExit(1)
            storage.clear_pending_approval()  # stale; safe to replace

        band_cfg = policy.bands.get(decision.band)
        backend_name = band_cfg.approval_backend if band_cfg else None

        pending = PendingApproval(
            amount=args.amount, description=args.description, reason=decision.reason,
            correlation_id=correlation_id,
        )
        try:
            storage.set_pending_approval(pending)
            print("Pending approval saved.")
        except Exception as e:
            print(f"error: failed to save pending approval: {e}", file=sys.stderr)
            raise SystemExit(1)

        try:
            storage.append_audit_entry(AuditEntry(
                event="escalated", amount=args.amount, description=args.description,
                band=decision.band, reason=decision.reason,
            ))
        except Exception as e:
            print(f"warning: failed to write audit entry: {e}", file=sys.stderr)
        _ledger_write(
            ledger, correlation_id=correlation_id, requester="cli:request",
            provider="custodian", action=args.skill or "cli-request",
            lifecycle_event="escalated", verdict=verdict_name, band=decision.band.value,
            amount=args.amount, currency="USD",
        )

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

        try:
            storage.append_audit_entry(AuditEntry(
                event="denied", amount=args.amount, description=args.description,
                band=decision.band, reason=decision.reason,
            ))
        except Exception as e:
            print(f"warning: failed to write audit entry: {e}", file=sys.stderr)
