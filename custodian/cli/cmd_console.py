"""Live, dependency-free operator firewall console."""
from __future__ import annotations

import os
import json
from pathlib import Path
import sys
import time

from custodian.control.policy import ApprovalPolicy, ApprovalRule
from custodian.control.filesystem_policy import FilesystemPolicy, FilesystemRule
from custodian.control.ledger_access_policy import LedgerAccessPolicy, LedgerGrant
from custodian.executor.capability import CapabilityStore

_CLEAR = "\x1b[2J\x1b[H"
_GREEN, _YELLOW, _RED, _DIM, _RESET = "\x1b[32m", "\x1b[33m", "\x1b[31m", "\x1b[2m", "\x1b[0m"


def _snooze_path(state_dir: Path) -> Path:
    return state_dir / "console-snoozes.json"


def _snoozes(state_dir: Path) -> dict[str, float]:
    try:
        value = json.loads(_snooze_path(state_dir).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    now = time.time()
    return {str(k): float(v) for k, v in value.items()
            if isinstance(v, (int, float)) and float(v) > now}


def _snooze(state_dir: Path, ident: str, *, seconds: int = 300) -> None:
    """Hide a request briefly without changing its authorization state."""
    values = _snoozes(state_dir)
    values[ident] = time.time() + seconds
    path = _snooze_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(values, sort_keys=True), encoding="utf-8")
    if os.name != "nt":
        tmp.chmod(0o600)
    os.replace(tmp, path)


def _key(timeout: float) -> str:
    if os.name == "nt":
        import msvcrt
        end = time.time() + timeout
        while time.time() < end:
            if msvcrt.kbhit(): return msvcrt.getwch().lower()
            time.sleep(.05)
        return ""
    import select, termios, tty
    fd = sys.stdin.fileno(); old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        return sys.stdin.read(1).lower() if ready else ""
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _confirm(prompt: str, timeout: float = 10.0) -> bool:
    print(f"\n  {_YELLOW}{prompt} [y/N]{_RESET} ", end="", flush=True)
    answer = _key(timeout)
    print(answer if answer else "(timeout)")
    return answer == "y"


def _remaining(record) -> str:
    seconds = max(0, int(record.expires_at - time.time()))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _age(record) -> str:
    seconds = int(time.time() - record.created_at)
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m{seconds % 60}s"


def _recent_blocks(state_dir: Path, limit: int = 3) -> list[dict]:
    """Return recent authenticated hard denials for persistent display.

    Merges two independent stores: Codex/OpenCode Guard's ReceiptChain and
    the UniversalLedger written by the general tool registry (which is what
    Talaria's HermesBridge feeds via registry.run()). Before this, denials
    from Talaria/registry-driven tool calls never appeared here -- the
    console only ever read the receipt chain, so "operator sees everything"
    silently didn't cover that whole path.
    """
    from custodian.codex_guard.receipts import ReceiptChain
    chain = ReceiptChain(state_dir)
    try:
        chain.verify()
        records = chain._records()
        denied = [r for r in records if r.get("verdict") == "denied"]
    except Exception as exc:
        denied = [{
            "tool": "receipt-chain",
            "reason": f"audit verification failed: {type(exc).__name__}",
            "ts": time.time(),
        }]

    try:
        from custodian.universal_ledger import UniversalLedger
        ledger = UniversalLedger(state_dir / "ledger.db")
        for row in ledger.by_verdict("denied", limit=limit):
            # codex_guard/opencode_guard mirror their own decisions into this
            # same ledger (see receipts.py's _mirror_to_universal_ledger) so
            # Talaria/registry activity shows up here too -- but that means
            # their denials are already fully covered by the receipt chain
            # above. Re-including them here would show every Codex/OpenCode
            # denial twice.
            if row.get("provider") in ("codex_guard", "opencode_guard"):
                continue
            denied.append({
                "tool": row.get("action", "unknown"),
                "reason": (row.get("metadata") or {}).get("reason", "denied by policy"),
                "ts": row.get("ts", time.time()),
                "verdict": "denied",
                "source": row.get("requester", "-"),
            })
    except Exception as exc:
        denied.append({
            "tool": "universal-ledger",
            "reason": f"ledger read failed: {type(exc).__name__}",
            "ts": time.time(),
        })

    denied.sort(key=lambda r: r.get("ts", 0))
    return denied[-limit:]


def _draw(state_dir: Path, message: str) -> tuple[ApprovalStore, CapabilityStore, list]:
    from custodian.codex_guard.approvals import ApprovalStore
    approvals = ApprovalStore(state_dir)
    capabilities = CapabilityStore(state_dir)
    hidden = _snoozes(state_dir)
    all_records = [r for r in approvals.list_records() if r.status == "pending" and r.expires_at > time.time()]
    all_caps = [r for r in capabilities.list_records() if r.status == "pending" and r.expires_at > time.time()]
    records = [r for r in all_records if r.approval_id not in hidden]
    caps = [r for r in all_caps if r.capability_id not in hidden]
    snoozed = len(all_records) + len(all_caps) - len(records) - len(caps)
    blocks = _recent_blocks(state_dir)
    now_str = time.strftime('%H:%M:%S')
    print(_CLEAR, end="")
    print("╔══════════════════════════════════════════════════════════════════════════════╗")
    print("║  CUSTODIAN CONTROL PLANE                         LIVE • FAIL-CLOSED         ║")
    print("╠══════════════════════════════════════════════════════════════════════════════╣")
    print(f"║  Pending {len(records)+len(caps):<4}  Snoozed {snoozed:<3}  Blocks {len(blocks):<4}  Harness {len(records):<4}     ║")
    print("╚══════════════════════════════════════════════════════════════════════════════╝")
    # Sorted oldest-first (not just CODEX-then-EXEC in creation order within
    # each group) so "the oldest pending request" -- what the operator
    # actions below are documented to apply to -- is genuinely combined[0],
    # and so a >12-item backlog still keeps the true oldest items in the
    # displayed slice below rather than truncating them out of view while an
    # unrendered item is still the one an action would silently apply to.
    combined = sorted(
        [("CODEX", r) for r in records] + [("EXEC", r) for r in caps],
        key=lambda pair: pair[1].created_at,
    )
    if not combined:
        print(f"\n  {_GREEN}✓ No actions waiting. Custodian is watching.{_RESET}")
    combined = combined[:12]
    for index, (source, record) in enumerate(combined, 1):
        ident = getattr(record, "approval_id", getattr(record, "capability_id", ""))
        digest = record.action_digest[:12]
        expiry = _remaining(record)
        age = _age(record)
        print(f"\n  {_YELLOW}{index:>2}. WAITING{_RESET}  {source:<5}  {expiry}  requester={record.requester}")
        print(f"      id={ident[:8]}…  digest={digest}…  age={age}")
    if blocks:
        print(f"\n  {_RED}BLOCKED ACTIONS — operator attention required{_RESET}")
        for block in reversed(blocks):
            tool = str(block.get("tool", "unknown"))[:28]
            reason = str(block.get("reason", "denied"))[:120]
            print(f"  {_RED}✕ {tool}: {reason}{_RESET}")
        print(f"  {_YELLOW}These are hard denials, not pending approvals. Review policy or use a trusted operator workflow.{_RESET}")
    print("\n────────────────────────────────────────────────────────────────────────────────")
    fs_rules = FilesystemPolicy(state_dir / "filesystem-policy.json").list()
    policy_rules = ApprovalPolicy(state_dir / "approval-policy.json").list()
    ledger_grants = LedgerAccessPolicy(state_dir / "ledger-access-policy.json").list()
    mode_counts: dict[str, int] = {}
    for r in policy_rules:
        mode_counts[r.mode] = mode_counts.get(r.mode, 0) + 1
    active_rules = len(policy_rules)
    modes = ", ".join(f"{c} {m}" for m, c in sorted(mode_counts.items()))
    print(f"  {_DIM}Policy: {active_rules} active rule(s) — {modes if modes else 'all ask (default)'}{_RESET}")
    print(f"  {_DIM}Filesystem scopes: {len(fs_rules)}{_RESET}")
    print(f"  {_DIM}Ledger access grants: {len(ledger_grants)} (no harness sees any receipts by default, not even its own){_RESET}")
    print(f"  {_YELLOW}[A]{_RESET} approve once    {_YELLOW}[D]{_RESET} deny    {_YELLOW}[I]{_RESET} ignore 5m    {_YELLOW}[L]{_RESET} lease (1h/25 uses)")
    print(f"  {_YELLOW}[F]{_RESET} filesystem scope    {_YELLOW}[G]{_RESET} ledger grant    {_YELLOW}[R]{_RESET} rules    {_YELLOW}[K]{_RESET} global stop    {_YELLOW}[Q]{_RESET} quit")
    print(f"  {_DIM}Approve-once: single-use — the next matching action consumes it.{_RESET}")
    print(f"  {_DIM}Lease: temporary rule with max uses.  Permanent: no expiry or limit.{_RESET}")
    print(f"  {_DIM}Actions apply to the oldest pending request (order shown).{_RESET}")
    if message: print(f"\n  {message}")
    return approvals, capabilities, combined


def run(args) -> int:
    from custodian.codex_guard.approvals import ApprovalError
    state_dir = Path(args.state_dir)
    policy = ApprovalPolicy(state_dir / "approval-policy.json")
    filesystem = FilesystemPolicy(state_dir / "filesystem-policy.json")
    ledger_access = LedgerAccessPolicy(state_dir / "ledger-access-policy.json")
    message = ""
    while True:
        try:
            approvals, capabilities, pending = _draw(state_dir, message)
        except Exception as exc:
            print(f"\n  {_RED}Error drawing dashboard: {exc}{_RESET}")
            time.sleep(2)
            message = ""
            continue
        key = _key(1.0); message = ""
        if not key: continue
        try:
            if key == "q": print(_RESET); return 0
            if key == "r":
                rules = policy.list()
                message = f"{len(rules)} active rule(s): " + ", ".join(
                    f"{r.mode}:{r.adapter}/{r.action_kind}" for r in rules[-4:]
                )
            elif key == "l":
                rule = ApprovalRule(mode="auto", adapter="codex", action_kind="write",
                                    workspace=str(Path.cwd()), expires_at=time.time() + 3600,
                                    max_uses=25)
                policy.add(rule)
                message = "One-hour local Codex write lease added (25 uses, auto-approve)."
            elif key == "f":
                print(_CLEAR, end="")
                print("Filesystem scope — deny always wins; blank model means every model")
                harness = input("Harness [codex]: ").strip() or "codex"
                model = input("Trusted model id [all]: ").strip() or "*"
                access = input("Access [read/write]: ").strip().lower()
                allow = tuple(p.strip() for p in input("Allow roots, comma separated: ").split(",") if p.strip())
                deny = tuple(p.strip() for p in input("Deny roots, comma separated: ").split(",") if p.strip())
                enforcement = input("Enforcement [routed/brokered]: ").strip() or "routed"
                try:
                    filesystem.add(FilesystemRule(
                        harness=harness, model=model, access=access,
                        allow_roots=allow, deny_roots=deny, enforcement=enforcement,
                    ))
                    message = f"Saved {access} scope for {harness}/{model}; deny overrides allow."
                except ValueError as exc:
                    message = f"Not saved: {exc}"
            elif key == "g":
                print(_CLEAR, end="")
                print("Ledger access grant — no harness sees any receipts by default, not even its own.")
                print("This grants ONE harness visibility into a ledger/receipt history — its own, another's, or both.")
                harness = input("Grant visibility TO harness [codex]: ").strip() or "codex"
                model = input("Trusted model id [all]: ").strip() or "*"
                can_view = tuple(
                    h.strip() for h in input("Can view harness(es), comma separated (or * for all): ").split(",")
                    if h.strip()
                )
                try:
                    ledger_access.add(LedgerGrant(harness=harness, model=model, can_view=can_view))
                    message = f"Granted {harness}/{model} visibility into: {', '.join(can_view)}."
                except ValueError as exc:
                    message = f"Not saved: {exc}"
            elif key == "k":
                if not _confirm("Stop all approvals? This adds a global deny rule."):
                    message = "Global stop cancelled."
                else:
                    rule = ApprovalRule(mode="deny", adapter="*", action_kind="*", tool="*")
                    policy.add(rule)
                    message = f"Global deny rule enabled: {rule.rule_id[:8]}…"
            elif key == "i" and pending:
                # combined/pending is sorted oldest-first in _draw() -- index 0
                # is genuinely "1." on screen, matching the documented
                # "applies to the oldest pending request."
                _, record = pending[0]
                ident = getattr(record, "approval_id", getattr(record, "capability_id", ""))
                _snooze(state_dir, ident)
                message = "Ignored for 5 minutes — still pending, never authorized."
            elif key in {"a", "d"} and pending:
                source, record = pending[0]
                try:
                    if source == "CODEX":
                        if key == "a":
                            # No expected_digest: record.action_digest is the
                            # same record being approved, so comparing it to
                            # itself can never fail -- a tautology, not a
                            # check. This interactive console's real safety
                            # property is the operator having just read the
                            # full displayed record (requester/digest/age)
                            # before pressing a key; it does not pretend to
                            # verify against an independently-obtained value
                            # the way `custodian executor approve --digest`
                            # does for the scripted/remote flow.
                            approvals.approve(record.approval_id, approved_by=args.operator)
                        else:
                            approvals.deny(record.approval_id, denied_by=args.operator)
                    else:
                        if key == "a":
                            capabilities.approve(record.capability_id, approved_by=args.operator)
                        else:
                            capabilities.deny(record.capability_id, denied_by=args.operator)
                    message = "Approved — single-use; consumed on next matching action." if key == "a" else "Denied."
                except (ApprovalError, Exception) as exc:
                    message = f"Not changed: {exc}"
        except Exception as exc:
            message = f"Key handler error: {exc}"


def register(sub, default_state_dir: str) -> None:
    parser = sub.add_parser("console", help="Live operator firewall for approvals and policy")
    parser.add_argument("--state-dir", default=default_state_dir)
    parser.add_argument("--operator", default=os.environ.get("USER", "operator"))
    parser.set_defaults(func=run)
