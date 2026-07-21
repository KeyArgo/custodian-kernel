from __future__ import annotations

import os
import sys
from pathlib import Path

from custodian.backends.twilio_verify import TwilioVerifyBackend
from custodian.exceptions import BackendConfigurationError
from custodian.storage.sqlite import SqliteStorage
from custodian.types import AuditEntry, Band
from custodian.universal_ledger import LedgerEvent, UniversalLedger


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
    db_path = state_dir / "custodian.db"

    try:
        storage = SqliteStorage(db_path)
    except Exception as e:
        print(f"error: failed to open state database: {e}", file=sys.stderr)
        raise SystemExit(1)

    pending = storage.get_pending_approval()
    if pending is None:
        print("error: no pending approval found", file=sys.stderr)
        raise SystemExit(1)

    ttl = int(os.environ.get("CUSTODIAN_PENDING_TTL_SECONDS", "600"))
    if pending.is_expired(ttl_seconds=ttl):
        storage.clear_pending_approval()
        print("error: pending approval has expired", file=sys.stderr)
        raise SystemExit(1)

    try:
        backend = _twilio_backend(state_dir)
        if not backend.check_response(args.code):
            print("error: verification code rejected by backend", file=sys.stderr)
            raise SystemExit(1)
    except BackendConfigurationError as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(1)
    except Exception as e:
        print(f"error: verification failed: {e}", file=sys.stderr)
        raise SystemExit(1)

    storage.clear_pending_approval()

    authority = storage.load_authority_state()
    actual_band = authority.band if authority is not None else Band.L2

    entry = AuditEntry(
        event="approved",
        amount=pending.amount,
        description=pending.description,
        band=actual_band,
        approved_by=args.approved_by,
        reason=pending.reason,
    )
    try:
        storage.append_audit_entry(entry)
    except Exception as e:
        print(f"warning: failed to write audit entry: {e}", file=sys.stderr)

    try:
        UniversalLedger(state_dir / "ledger.db").append(LedgerEvent(
            correlation_id=pending.correlation_id, requester="cli:approve",
            provider="custodian", action="cli-request", lifecycle_event="approved",
            verdict="escalation_required", band=actual_band.value,
            approver=args.approved_by, amount=pending.amount, currency="USD",
        ))
    except Exception as e:
        print(f"warning: failed to write ledger event: {e}", file=sys.stderr)

    # An operator-approved escalation consumes the session budget the same as
    # an autonomous spend -- otherwise approvals are invisible to the cap.
    if authority is not None:
        try:
            storage.record_spend(pending.amount)
        except Exception as e:
            print(f"warning: failed to record spend: {e}", file=sys.stderr)

    print(f"Approved: ${pending.amount:.2f} for '{pending.description}' by {args.approved_by}")
