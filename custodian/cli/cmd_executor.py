"""custodian executor -- run and approve requests against the delegated
executor, the separate process that holds the only code path allowed to
actually run a governed skill script (see custodian/executor/)."""
from __future__ import annotations

import hmac
import os
import sys
import time
from pathlib import Path
from custodian.executor.capability import CapabilityError, CapabilityStore
from custodian.tools.registry import _state_dir


def _default_socket_path() -> Path:
    return _state_dir() / "executor.sock"


def _resolve_capability(
    store: CapabilityStore, capability_id: str, *, now: float | None = None,
) -> str:
    """Return a concrete capability_id, resolving 'latest' when appropriate.

    Raises CapabilityError on any problem so callers keep a single error path.
    """
    if capability_id != "latest":
        return capability_id

    ts = now if now is not None else time.time()
    pending = []
    paths = store.capabilities_dir.glob("*.json") if store.capabilities_dir.exists() else ()
    for path in paths:
        try:
            candidate = store.get(path.stem)
        except (OSError, CapabilityError):
            continue
        if candidate.status == "pending" and candidate.expires_at >= ts:
            pending.append(candidate)
    if not pending:
        raise CapabilityError("no unexpired pending capabilities")
    requesters = {item.requester for item in pending}
    if len(requesters) > 1:
        # 'latest' used to mean "the newest pending capability regardless of
        # who requested it" -- an operator approving/denying their own
        # session's latest request could silently act on a completely
        # different requester's pending capability instead (a benign
        # concurrent agent, or one racing to submit right before the
        # operator hits enter). Refuse the ambiguous shorthand rather than
        # guess; the operator must name the exact capability_id.
        raise CapabilityError(
            "multiple requesters have pending capabilities -- 'latest' is "
            "ambiguous; specify the exact capability_id instead"
        )
    return max(pending, key=lambda item: item.created_at).capability_id


def cmd_executor_start(args) -> int:
    from custodian.executor.service import serve_forever

    skills_root = Path(args.skills_root) if args.skills_root else None
    if skills_root is None:
        from custodian.tools.registry import default_registry
        skills_root = default_registry().skills_root
    socket_path = Path(args.socket) if args.socket else _default_socket_path()

    print(f"Custodian executor listening on {socket_path}")
    print(f"Skills root: {skills_root}")
    print("Ctrl-C to stop.")
    try:
        serve_forever(skills_root, socket_path)
    except KeyboardInterrupt:
        print("\nExecutor stopped.")
    return 0


def cmd_executor_approve(args) -> int:
    state_dir = Path(args.state_dir) if args.state_dir else _state_dir()
    store = CapabilityStore(state_dir)

    try:
        capability_id = _resolve_capability(store, args.capability_id)
    except CapabilityError:
        return 1

    # Read *before* approve so the operator can see the digest even if the
    # call fails (fail-closed: we never approve what we cannot show).
    try:
        cap = store.get(capability_id)
    except CapabilityError:
        return 1

    print(f"Pending capability {cap.capability_id} (requester={cap.requester!r}):")
    print(f"  action digest : {cap.action_digest}")
    print(f"  created at    : {cap.created_at}")
    print(f"  expires at    : {cap.expires_at}")

    if args.digest is not None:
        if not hmac.compare_digest(str(args.digest), str(cap.action_digest)):
            print(
                f"error: displayed digest does not match capability digest; "
                f"refusing to approve to prevent approval of a different action",
                file=sys.stderr,
            )
            return 1
        print("  digest check  : OK -- action matches provided digest")

    if not args.approved_by.strip():
        print("error: operator identity is required (--approved-by NAME)", file=sys.stderr)
        return 2

    try:
        approved = store.approve(
            capability_id,
            approved_by=args.approved_by,
            expected_digest=args.digest,
        )
    except CapabilityError:
        return 1

    print(
        f"Approved capability {approved.capability_id} (requester={approved.requester!r}). "
        f"Resend the identical request to consume it and execute."
    )
    return 0


def cmd_executor_deny(args) -> int:
    state_dir = Path(args.state_dir) if args.state_dir else _state_dir()
    store = CapabilityStore(state_dir)

    denied_by = args.denied_by or os.environ.get("USER") or os.environ.get("USERNAME")
    if not denied_by:
        print("error: operator identity is required (--denied-by NAME)", file=sys.stderr)
        return 2

    try:
        capability_id = _resolve_capability(store, args.capability_id)
    except CapabilityError:
        return 1

    try:
        cap = store.get(capability_id)
    except CapabilityError:
        return 1

    print(f"Deny pending capability {cap.capability_id} (requester={cap.requester!r}):")
    print(f"  action digest : {cap.action_digest}")
    print(f"  created at    : {cap.created_at}")
    print(f"  expires at    : {cap.expires_at}")

    if args.digest is not None:
        if not hmac.compare_digest(str(args.digest), str(cap.action_digest)):
            print(
                f"error: displayed digest does not match capability digest; "
                f"refusing to deny a different action than expected",
                file=sys.stderr,
            )
            return 1
        print("  digest check  : OK -- action matches provided digest")

    print(f"  denied by     : {denied_by}")

    try:
        denied = store.deny(capability_id, denied_by=denied_by)
        print(f"Denied capability {denied.capability_id} (requester={denied.requester!r}).")
        return 0
    except CapabilityError:
        return 1


def register(sub) -> None:
    """Attach the `executor` subcommand tree to the main parser."""
    parser = sub.add_parser(
        "executor",
        help="Run and approve requests against the delegated executor (separate-process execution)",
        description=(
            "The delegated executor is a separate process that holds the only "
            "code path allowed to actually run a governed skill script -- the "
            "calling agent's own process can only propose an action over a "
            "Unix socket and never executes anything itself. An escalated "
            "action creates a signed, single-use, digest-bound capability; "
            "approve it here, then resend the identical request to consume it."
        ),
    )
    esub = parser.add_subparsers(dest="executor_command", required=True)

    sp = esub.add_parser("start", help="Start the executor process (blocks)")
    sp.add_argument("--skills-root", help="Skills directory (default: the bundled/dev skills root)")
    sp.add_argument("--socket", help="Unix socket path (default: <state-dir>/executor.sock)")
    sp.set_defaults(func=cmd_executor_start)

    sp = esub.add_parser("approve", help="Approve a pending capability by id")
    sp.add_argument("capability_id", help="Capability UUID, or 'latest'")
    sp.add_argument("--approved-by", required=True, help="Operator identity for the audit trail")
    sp.add_argument(
        "--digest",
        help="Full action digest (64-char hex) for verification before approval. "
             "If provided and it does not match the capability, approval is rejected.",
    )
    sp.add_argument("--state-dir", help="State directory (default: ~/.custodian or $CUSTODIAN_STATE_DIR)")
    sp.set_defaults(func=cmd_executor_approve)

    sp = esub.add_parser("deny", help="Deny a pending capability")
    sp.add_argument("capability_id", help="Capability UUID, or 'latest'")
    sp.add_argument("--denied-by", help="Operator identity (falls back to $USER)")
    sp.add_argument("--digest", help="Full action digest (64-char hex) to verify before denying.")
    sp.add_argument("--state-dir", help="State directory (default: ~/.custodian or $CUSTODIAN_STATE_DIR)")
    sp.set_defaults(func=cmd_executor_deny)
