"""Harness-neutral action-evaluation engine shared by every Custodian guard.

Moved here from ``custodian.codex_guard.mcp_server`` -- that module's
``evaluate_guard_action`` was already written to serve "any supported
harness" (Codex, Claude, OpenCode) via its ``harness`` keyword, but it lived
inside codex-guard's own package, which meant every other guard adapter had
to depend on ``custodian-codex-guard`` just to reach it. That's the exact
thing ``tests/test_architecture_boundaries.py::test_no_guard_imports_another_guard``
now forbids: a guard adapter (Claude/OpenCode/...) must never require another
guard adapter's package, only Kernel's.

``custodian.codex_guard.mcp_server`` re-exports these same names for
backward compatibility with already-published callers (its own ``handle()``
stdio loop, and anything else that imported this function from that path
before the move); the MCP JSON-RPC transport itself (``handle``, ``main``,
``_text_result``, ``_server_version``) stays there -- that part genuinely is
Codex-specific.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from custodian.guard_core.approvals import ApprovalError, ApprovalStore, action_digest
from custodian.guard_core.guard import ActionKind, GuardDecision, evaluate_action
from custodian.guard_core.paladin_bridge import credential_guidance, refs_in_arguments
from custodian.guard_core.receipts import ReceiptChain
from custodian.control.policy import ApprovalPolicy, Proposal
from custodian.control.filesystem_policy import FilesystemPolicy
from custodian.control.settings import ControlSettingsStore
from custodian.control.gate_policy import GateContext, GatePolicy
from custodian.control.action_gates import gates_for as _gates_for
from custodian.adapters.builtin._paths import path_values, resolve as canonicalize


_RECOVERY_TOOL_SUFFIXES = (
    "guard_action", "verify_receipts", "list_receipts",
    "_get_app_permissions", "_update_app_permissions",
    "custodian_settings", "gate_settings",
)


def _recovery_tool(tool: str) -> bool:
    normalized = tool.strip().lower()
    return any(normalized.endswith(suffix) for suffix in _RECOVERY_TOOL_SUFFIXES)


def _effective_workspace(declared: str, arguments: dict[str, Any]) -> str:
    """Prefer a tool's concrete working directory over the session root."""
    nested = arguments.get("workdir", arguments.get("cwd"))
    if not isinstance(nested, str) or not nested.strip():
        return declared
    candidate = Path(nested).expanduser()
    if not candidate.is_absolute():
        candidate = Path(declared).expanduser() / candidate
    try:
        return str(candidate.resolve())
    except (OSError, RuntimeError, ValueError):
        return nested


def _argument_paths(arguments: dict[str, Any], workspace: str) -> list[str]:
    try:
        result = []
        for raw in path_values(arguments):
            if not os.path.isabs(os.path.expanduser(raw)):
                raw = str(Path(workspace) / raw)
            resolved = canonicalize(raw)
            if resolved not in result:
                result.append(resolved)
        return result
    except (OSError, RuntimeError, TypeError, ValueError):
        return []


def _state_dir() -> Path:
    # Env var name kept as-is (not renamed to something harness-neutral)
    # for backward compatibility -- already-published codex-guard installs
    # (and this session's own test suite) set CUSTODIAN_CODEX_GUARD_STATE_DIR
    # for isolation. It names the *first* guard that used it, not the only
    # one that does now; every harness's receipts/approvals share this dir.
    configured = os.environ.get("CUSTODIAN_CODEX_GUARD_STATE_DIR")
    return Path(configured).expanduser() if configured else Path.home() / ".custodian"


def _evaluate_with_paladin_guidance(
    *,
    tool: str,
    action_kind: str,
    arguments: dict[str, Any] | None,
    workspace: str,
    intent: str = "",
    forbidden_paths: list[str] | None = None,
    allow_paths: list[str] | None = None,
    allow_broad_workspace: bool = False,
) -> GuardDecision:
    """The bare Kernel decision, plus a Paladin vault-egress hint appended to
    a credential-class escalation reason -- equivalent to what
    ``custodian.codex_guard.guard.evaluate_action`` did for Codex alone,
    now available to every harness since ``paladin_bridge`` lives in Kernel
    too."""
    decision = evaluate_action(
        tool=tool, action_kind=action_kind, arguments=arguments,
        workspace=workspace, intent=intent, forbidden_paths=forbidden_paths,
        allow_paths=allow_paths, allow_broad_workspace=allow_broad_workspace,
    )
    if decision.verdict != "escalation_required":
        return decision
    try:
        kind = ActionKind(decision.action_kind)
        if kind is ActionKind.CREDENTIAL or refs_in_arguments(arguments or {}):
            guidance = credential_guidance(arguments or {})
            if guidance:
                return GuardDecision(
                    verdict=decision.verdict, action_kind=decision.action_kind,
                    reason=decision.reason + guidance, band=decision.band,
                    enforcement_required=decision.enforcement_required,
                    warnings=decision.warnings,
                )
    except Exception:
        pass
    return decision


def evaluate_guard_action(args: dict[str, Any], *, harness: str = "codex") -> dict[str, Any]:
    """Evaluate one exact proposal for any supported harness.

    Harness identity is supplied by the trusted adapter, never by model tool
    arguments. Operator policy is applied to every action, including otherwise
    autonomous reads/writes, so an explicit deny/ask rule cannot be skipped.
    """
    if not harness or len(harness) > 64:
        raise ValueError("invalid harness identity")
    chain = ReceiptChain(_state_dir())
    try:
        model = os.environ.get("CUSTODIAN_TRUSTED_MODEL_ID", "*")
        requested_kind = str(args.get("action_kind", ""))
        declared_workspace = str(args.get("workspace", ""))
        tool_arguments = args.get("arguments")
        if not isinstance(tool_arguments, dict):
            tool_arguments = {}
        workspace = _effective_workspace(declared_workspace, tool_arguments)
        session_id = str(args.get("session_id", "default"))
        paths = _argument_paths(tool_arguments, workspace)
        path = paths[0] if paths else ""
        gate_policy = GatePolicy(_state_dir() / "gate-policy.json")
        filesystem_gate = (
            "filesystem_read" if requested_kind == "read" else "filesystem_write"
        )
        explicit_broad_allow = any(
            (
                mode == "allow"
                and not rule_id.startswith("default:")
                and scope in {"path", "project"}
            )
            for mode, rule_id, scope in (
                gate_policy.decide(GateContext(
                    gate=filesystem_gate, harness=harness,
                    tool=str(args.get("tool", "")), session_id=session_id,
                    project=workspace, path=candidate_path,
                ))
                for candidate_path in (paths or [""])
            )
        )
        access = "read" if requested_kind == "read" else "write"
        fs_config = FilesystemPolicy(_state_dir() / "filesystem-policy.json").fence_config(
            harness=harness, model=model, access=access,
            inherited_allow=[workspace],
            # `~/.codex` (and `~/.claude`) hold the guard's own hook wiring and
            # policy; fencing them here stops a bash redirect like
            # `echo ... >> ~/.codex/config.toml` from disabling the guard the way
            # only an apply_patch write was already caught (guard.py
            # _SENSITIVE_WRITE_PATH). Self-protection, not user data.
            # OpenCode's guard plugin lives under `~/.config/opencode/plugins/`
            # (XDG convention, unlike Codex/Claude's direct dotfile homes) --
            # see opencode_guard/cli.py's _plugin_path(). Same bash-redirect
            # self-disable risk applies there too. This literal doesn't
            # follow a custom $XDG_CONFIG_HOME override, matching the other
            # entries here, which are also plain literals.
            inherited_deny=["~/.ssh", "~/.aws", "~/.config/gcloud", "~/.kube",
                            "~/.codex", "~/.claude", "~/.config/opencode"],
        )
        decision = _evaluate_with_paladin_guidance(
            tool=args.get("tool", ""), action_kind=requested_kind,
            arguments=tool_arguments, workspace=workspace,
            intent=args.get("intent", ""), forbidden_paths=fs_config["forbidden_paths"],
            allow_paths=fs_config["allow_paths"],
            allow_broad_workspace=(
                fs_config["source"] != "harness-default"
                or _recovery_tool(str(args.get("tool", "")))
                or explicit_broad_allow
            ),
        ).to_dict()
        decision["declared_workspace"] = declared_workspace
        decision["effective_workspace"] = workspace
        decision["filesystem_policy"] = {
            "harness": harness, "model": model, "source": fs_config["source"],
            "enforcement": fs_config["enforcement"],
        }
        control_settings = ControlSettingsStore(
            _state_dir() / "control-settings.json"
        ).load()
        if (
            decision["verdict"] == "denied"
            and control_settings.enforcement_for(harness) == "open"
        ):
            observed_reason = decision["reason"]
            decision.update(
                verdict="autonomous",
                reason=(
                    "open monitor mode observed a mandatory detector finding; "
                    "execution is allowed"
                ),
                band="L1",
                monitor_observation=observed_reason,
            )
        requester = args["requester"]
        proposal_digest = action_digest(
            tool=args["tool"], action_kind=decision["action_kind"],
            arguments=tool_arguments, workspace=workspace,
            requester=requester,
            policy_version=args.get("policy_version", "default"),
        )
        proposal = Proposal(
            adapter=harness, action_kind=decision["action_kind"],
            tool=args["tool"], requester=requester, workspace=workspace,
        )
        legacy_mode, legacy_rule_id = ApprovalPolicy(
            _state_dir() / "approval-policy.json"
        ).decide(proposal)

        entered = []
        for gate in _gates_for(
            tool=args["tool"], kind=decision["action_kind"],
            arguments=tool_arguments, workspace=workspace, paths=paths,
        ):
            candidate_paths = paths if gate in {
                "filesystem_read", "filesystem_write", "outside_workspace",
            } and paths else [""]
            candidates = [
                gate_policy.decide(GateContext(
                    gate=gate, harness=harness, tool=args["tool"],
                    session_id=session_id, project=workspace,
                    path=candidate_path, action_digest=proposal_digest,
                ))
                for candidate_path in candidate_paths
            ]
            priority = {"allow": 0, "ask": 1, "block": 2}
            gate_mode, gate_rule_id, scope = max(
                candidates, key=lambda item: priority[item[0]]
            )
            entered.append({
                "gate": gate, "mode": gate_mode, "rule_id": gate_rule_id,
                "scope": scope,
            })
        decision["gates"] = entered
        decision["notification"] = {
            "event": "gate_decision",
            "tool": str(args["tool"])[:128],
            "destination": path or workspace,
            "result": decision["verdict"],
            "controls": ["Block", "Ask next time", "Allow for session", "Settings"],
        }

        # Mandatory adapter denials always win. Granular block/ask/allow is
        # next. A stored legacy rule remains effective during migration.
        blocked = next((g for g in entered if g["mode"] == "block"), None)
        asked = next((g for g in entered if g["mode"] == "ask"), None)
        if decision["verdict"] != "denied" and blocked:
            decision.update(
                verdict="denied", reason=f"{blocked['gate']} gate is blocked",
                policy_rule_id=blocked["rule_id"], policy_scope=blocked["scope"],
                band="L4",
            )
        elif decision["verdict"] != "denied" and legacy_mode == "deny":
            decision.update(verdict="denied", reason="blocked by operator policy",
                            policy_rule_id=legacy_rule_id)
        elif decision["verdict"] != "denied" and asked:
            decision.update(verdict="escalation_required",
                            reason=f"{asked['gate']} gate requires approval",
                            policy_rule_id=asked["rule_id"],
                            policy_scope=asked["scope"], band="L3")
        elif (
            decision["verdict"] != "denied"
            and legacy_mode == "ask"
            and legacy_rule_id
        ):
            decision.update(
                verdict="escalation_required",
                reason="matching legacy operator policy requires approval",
                policy_rule_id=legacy_rule_id, band="L3",
            )
        elif (
            decision["verdict"] == "escalation_required"
            and legacy_mode == "auto"
            and legacy_rule_id
        ):
            # Preserve explicit legacy auto-rule evidence during migration:
            # the exact action is still minted, approved, and consumed below.
            pass
        elif decision["verdict"] == "escalation_required":
            # The old action band escalated this action, but every granular
            # gate that applies is explicitly/default allowed.
            decision.update(
                verdict="autonomous",
                reason="all entered gates allow this action with auditing",
                band="L1",
            )

        if decision["verdict"] == "escalation_required":
            digest = proposal_digest
            store = ApprovalStore(_state_dir())
            approval_id = args.get("approval_id")
            # Hook-based harnesses can't replay an approval_id through a tool
            # call, so bind the identical re-run to an out-of-band operator
            # approval by its digest instead. Only ever finds an approval the
            # operator already granted for this exact action + requester.
            if not approval_id:
                approval_id = store.find_approved(digest=digest, requester=requester)
            if approval_id:
                store.consume(approval_id, digest=digest, requester=requester)
                decision.update(verdict="approved",
                                reason="exact action approved once by the human operator",
                                approval_id=approval_id)
            elif legacy_mode == "auto" and legacy_rule_id:
                exact = store.request(digest=digest, requester=requester, harness=harness)
                store.approve(exact.approval_id, approved_by=f"policy:{legacy_rule_id}",
                              expected_digest=digest)
                store.consume(exact.approval_id, digest=digest, requester=requester)
                decision.update(verdict="approved",
                                reason="exact action approved by scoped operator policy",
                                approval_id=exact.approval_id,
                                policy_rule_id=legacy_rule_id)
            else:
                pending = store.request(digest=digest, requester=requester, harness=harness)
                decision.update(
                    approval_id=pending.approval_id, action_digest=digest,
                    approval_expires_at=pending.expires_at,
                    next_step=("Open `custodian console`, or ask the operator to run: "
                               f"custodian-codex approve {pending.approval_id} --digest {digest}"),
                )
        decision["notification"]["result"] = decision["verdict"]
        receipt = chain.append(decision, tool=args.get("tool", ""),
                               session_id=session_id, harness=harness)
        decision["receipt"] = {"timestamp": receipt["ts"], "chain_mac": receipt["mac"]}
        return decision
    except ApprovalError as exc:
        denied = {"verdict": "denied", "reason": str(exc),
                  "action_kind": str(args.get("action_kind", "unknown")),
                  "band": "L4", "enforcement_required": True}
        receipt = chain.append(denied, tool=args.get("tool", ""),
                               session_id=args.get("session_id", "default"), harness=harness)
        denied["receipt"] = {"timestamp": receipt["ts"], "chain_mac": receipt["mac"]}
        return denied
    except Exception as exc:
        denied = {
            "verdict": "denied",
            "reason": f"guard evaluation failed closed ({type(exc).__name__})",
            "action_kind": str(args.get("action_kind", "unknown")),
            "band": "L4",
            "enforcement_required": True,
        }
        try:
            receipt = chain.append(
                denied, tool=str(args.get("tool", "")),
                session_id=str(args.get("session_id", "default")),
                harness=harness,
            )
            denied["receipt"] = {
                "timestamp": receipt["ts"], "chain_mac": receipt["mac"],
            }
        except Exception:
            pass
        return denied


def notification_line(decision: dict[str, Any]) -> str:
    """One human-readable line for a gate crossing worth telling the operator
    about, or "" when there's nothing worth surfacing.

    Deliberately narrow, on two axes:

    * Only an ``autonomous`` verdict (the action auto-proceeded with no
      human involved) counts. An ``approved`` verdict was already a human
      decision — they don't need telling about their own approval.
    * Only gates in ``ASK_BY_DEFAULT`` (money/credentials/destructive/
      git_write/production/network/governance) count, and only when they
      resolved to ``allow``. ``filesystem_read``/``filesystem_write``/
      ``outside_workspace``/``shell``/``package_install`` are *never*
      ask-gated regardless of open/protected enforcement (see
      ``GATES - ASK_BY_DEFAULT`` in gate_policy.py) — counting those would
      fire this notice on every ordinary file read, drowning the signal
      the operator actually wants: "this passed through the open/protected
      toggle," not "a tool call happened."
    """
    if decision.get("verdict") != "autonomous":
        return ""
    from custodian.control.gate_policy import ASK_BY_DEFAULT
    open_gates = sorted({
        g["gate"] for g in (decision.get("gates") or [])
        if g.get("mode") == "allow" and g.get("gate") in ASK_BY_DEFAULT
    })
    if not open_gates:
        return ""
    notification = decision.get("notification") or {}
    tool = notification.get("tool") or "action"
    destination = notification.get("destination") or ""
    where = f" on {destination}" if destination else ""
    return (
        f"[Custodian] {tool}{where} auto-allowed through open gate(s): "
        f"{', '.join(open_gates)}. Run `custodian gates protect` to require "
        "approval for these."
    )


# action_kinds worth calling out in an aggregate summary as "this passed with
# no human involved" -- read/write/test are never ask-gated regardless of
# open/protected enforcement (see ASK_BY_DEFAULT in control/gate_policy.py),
# so counting them would bury the signal under routine file/shell activity.
# Coarser than notification_line's own per-decision gate check (receipts only
# persist action_kind, not the full entered-gates list), but the closest
# available proxy from historical data.
NOTABLE_ACTION_KINDS = frozenset({
    "network", "credential", "destructive", "production", "money", "governance",
})


def open_gate_summary(chain: ReceiptChain, *, harness: str) -> dict[str, int]:
    """Count this harness's own autonomous (no human involved) receipts by
    notable action_kind, for a pull-based "what's been auto-passing" status
    view -- e.g. `custodian-codex status` / `custodian-claude status`.

    ``harness`` filtering matters: the receipt chain is one shared file
    (``ReceiptChain(_state_dir())``) written by every adapter that calls
    ``evaluate_guard_action``, distinguished only by each record's own
    ``harness`` field. An unfiltered count attributes every other adapter's
    activity to whichever CLI happens to be asking -- e.g. an OpenCode auto-
    allow would inflate ``custodian-codex status``'s number too.
    """
    counts: dict[str, int] = {}
    try:
        records = chain.records()
    except Exception:
        return counts
    for record in records:
        if record.get("harness") != harness or record.get("verdict") != "autonomous":
            continue
        kind = record.get("action_kind")
        if kind in NOTABLE_ACTION_KINDS:
            counts[kind] = counts.get(kind, 0) + 1
    return counts
