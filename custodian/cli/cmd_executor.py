"""custodian executor -- run and approve requests against the delegated
executor, the separate process that holds the only code path allowed to
actually run a governed skill script (see custodian/executor/)."""
from __future__ import annotations

import sys
from pathlib import Path

from custodian.executor.capability import CapabilityError, CapabilityStore
from custodian.tools.registry import _state_dir


def _default_socket_path() -> Path:
    return _state_dir() / "executor.sock"


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
        cap = store.approve(args.capability_id, approved_by=args.approved_by)
    except CapabilityError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(
        f"Approved capability {cap.capability_id} (requester={cap.requester!r}). "
        f"Resend the identical request to consume it and execute."
    )
    return 0


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
    sp.add_argument("capability_id")
    sp.add_argument("--approved-by", required=True, help="Operator identity for the audit trail")
    sp.add_argument("--state-dir", help="State directory (default: ~/.custodian or $CUSTODIAN_STATE_DIR)")
    sp.set_defaults(func=cmd_executor_approve)
