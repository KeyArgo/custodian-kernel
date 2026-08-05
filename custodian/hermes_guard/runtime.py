"""HermesGuardRuntime — the OSS runtime the Hermes plugin drives.

This is the adapter that turns a Hermes ``pre_tool_call`` / 
``transform_tool_result`` event into a Custodian decision. It is the
enforcement boundary on the Hermes side, so it is written to fail closed
under every failure mode: a malformed event, an unavailable control plane,
an expired/consumed approval, or any unexpected exception resolves to an
explicit denial or output suppression -- never to silence.

The runtime never decides policy itself. Every pre-action decision comes
from the shared decision engine
(:func:`custodian.codex_guard.mcp_server.evaluate_guard_action`) with the
trusted harness identity ``hermes``; receipts and approvals live in the
same operator-owned state directory the other harness adapters use.

Required runtime surface (kept stable for the repository-owned plugin):

* ``HermesGuardRuntime(vault=None, notifier=None)``
* ``.pipeline``          -- compiled post-action pipeline (compat probe;
                            initialization failure must fail closed)
* ``.policy``            -- operator-facing settings mapping
* ``.evaluate_pre(...)`` -- decision for a proposed tool call
* ``.wait_for_approval(...)`` -- bounded, digest-bound approval wait
* ``.inspect_result(...)``    -- post-action redaction / suppression
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable, Optional

from custodian.adapters import ActionContext, AdapterPipeline
from custodian.adapters.builtin import PiiRedactor, PromptInjectionGuard, SecretLeakGuard
from custodian.codex_guard.approvals import ApprovalError, ApprovalStore
from custodian.codex_guard.mcp_server import _state_dir
from custodian.codex_guard.receipts import ReceiptChain

from .bridge import evaluate_tool
from .contract import (
    HERMES_GUARD_CONTRACT_VERSION,
    HermesDecision,
    HermesToolEvent,
)

#: Output string substituted for a tool result that a post-action guard
#: denied or that the guard pipeline failed to evaluate. Deliberately
#: value-free; the model must not see the suppressed bytes.
_SUPPRESSED = "[hermes-guard] output suppressed: a post-action guard denied this result"

#: Approval wait window bounds. An operator cannot be expected to approve
#: within a sub-second window, and a runaway agent must not be able to pin
#: the session for hours waiting on an approval that will never come.
_MIN_WAIT_SECONDS = 0.0
_MAX_WAIT_SECONDS = 3600.0
_POLL_INTERVAL_SECONDS = 1.0


class HermesGuardRuntime:
    """Fail-closed Hermes tool-call guard backed by the shared Custodian core."""

    def __init__(
        self,
        vault: Any = None,
        notifier: Optional[Callable[[str], None]] = None,
        *,
        state_dir: Optional[Path] = None,
    ) -> None:
        # `vault` is accepted for interface compatibility with deployment
        # shims that open a Paladin vault for egress/credential metadata.
        # The runtime itself never reads vault material; the shared engine
        # decides credential actions. A missing vault must never crash the
        # plugin or block tool calls.
        self.vault = vault
        self.notifier: Callable[[str], None] = notifier or (lambda _message: None)
        self._state_dir: Path = Path(state_dir) if state_dir is not None else _state_dir()
        self._policy: dict[str, Any] = {
            "harness": "hermes",
            "contract_version": HERMES_GUARD_CONTRACT_VERSION,
            "operator": {
                # Bounded, operator-tunable default for how long a tool
                # call may wait on an approval before failing closed.
                "approval_wait_seconds": _bounded_wait(
                    os.environ.get("TALARIA_APPROVAL_WAIT_SECONDS", "300")
                ),
            },
        }
        # Compiled once per process, mirroring the reference prototype: the
        # post-action pipeline is built at construction, so any
        # initialization problem surfaces as a construction failure and the
        # plugin blocks the first tool call instead of running unguarded.
        # `pipeline` is also the compatibility probe the plugin pokes.
        self._pipeline: AdapterPipeline = AdapterPipeline([
            SecretLeakGuard(),
            PiiRedactor(),
            PromptInjectionGuard({"strict": True}),
        ])

    # -- operator-facing surface ------------------------------------------

    @property
    def pipeline(self) -> AdapterPipeline:
        """Compiled post-action pipeline. Also serves as the init probe."""
        return self._pipeline

    @property
    def policy(self) -> dict[str, Any]:
        """Operator-facing settings. Never contains policy logic itself."""
        return self._policy

    @property
    def contract_version(self) -> str:
        return HERMES_GUARD_CONTRACT_VERSION

    # -- pre-action --------------------------------------------------------

    def evaluate_pre(
        self,
        tool_name: str = "",
        args: Any = None,
        *,
        approval_id: str = "",
        requester: str = "hermes:agent",
        workspace: Optional[str] = None,
        correlation_id: str = "",
        session_id: str = "",
        task_id: str = "",
    ) -> HermesDecision:
        """Evaluate one proposed tool call; returns a fail-closed decision.

        ``workspace`` comes from the trusted plugin layer (Hermes session
        cwd) and defaults to the process cwd. The requester identity is
        ``hermes:<session>``-shaped when a session is known, else the
        supplied requester -- never derived from model arguments.
        """
        workspace = workspace or os.getcwd()
        effective_session = session_id or requester
        effective_requester = requester
        if session_id and requester == "hermes:agent":
            effective_requester = f"hermes:{session_id[:128]}"
        payload: dict[str, Any] = {
            "tool": str(tool_name),
            "arguments": dict(args) if isinstance(args, dict) else {},
            "workspace": workspace,
            "requester": effective_requester,
            "session_id": effective_session[:128],
            "task_id": str(task_id)[:128],
            "correlation_id": str(correlation_id)[:128],
            "intent": f"Hermes {tool_name} call",
        }
        if isinstance(approval_id, str) and approval_id:
            payload["approval_id"] = approval_id
        try:
            decision = evaluate_tool(payload)
        except Exception as exc:  # pragma: no cover - exact exception is irrelevant
            self.notifier(f"BLOCKED — guard evaluation failed: {exc}")
            return HermesDecision(
                verdict="denied", allowed=False, action_kind="unknown",
                reason="guard evaluation failed",
                notification="[hermes-guard] unavailable; tool call blocked (guard evaluation failed)",
            )
        wrapped = HermesDecision.from_engine(decision)
        if not wrapped.allowed:
            self.notifier(
                f"{wrapped.verdict} {wrapped.action_kind} ({tool_name}): {wrapped.reason}"
            )
        return wrapped

    def wait_for_approval(
        self,
        tool_name: str = "",
        args: Any = None,
        *,
        approval_id: str,
        requester: str = "hermes:agent",
        workspace: Optional[str] = None,
        correlation_id: str = "",
        session_id: str = "",
        task_id: str = "",
        timeout_seconds: float = 300.0,
    ) -> HermesDecision:
        """Wait (bounded) for an operator decision on a pending approval.

        The approval is bound to the exact action digest the operator
        approved; this method only ever authorizes the exact action +
        requester that the record names. Any mismatch, expiry, denial,
        timeout, or store failure resolves to ``denied``.

        To enforce that binding, this method does NOT consume the record
        using the digest stored *on* the record. It re-runs the shared
        engine with the exact current invocation (tool, args, workspace,
        requester, session) so the engine recomputes the action digest
        from what the model is about to do. If any execution-relevant
        field changed since the operator approved, the recomputed digest
        won't match and the engine fails closed -- the approval cannot be
        replayed against a different action.

        ``escalation_required`` from :meth:`evaluate_pre` is *not*
        permission; the plugin must call this (or otherwise obtain the
        exact approval) before the tool executes.
        """
        if not isinstance(approval_id, str) or not approval_id:
            return self._denied("missing approval id; failing closed")
        workspace = workspace or os.getcwd()
        store = ApprovalStore(self._state_dir)
        deadline = time.monotonic() + _bounded_wait(str(timeout_seconds))
        while True:
            try:
                record = store.get(approval_id)
            except ApprovalError as exc:
                return self._denied(f"approval not found or unreadable ({exc})")
            except Exception as exc:  # pragma: no cover - store tamper etc.
                return self._denied(f"approval store failure ({type(exc).__name__})")
            if record.status == "approved" and record.consumed_at is None:
                # Re-evaluate the exact current action through the shared
                # engine. The engine recomputes the digest from the current
                # invocation and consumes the approval only if it binds to
                # this exact action + requester. A changed tool, argument,
                # workspace, requester, or session fails closed here.
                decision = self.evaluate_pre(
                    tool_name=tool_name,
                    args=args,
                    approval_id=approval_id,
                    requester=requester,
                    workspace=workspace,
                    correlation_id=correlation_id,
                    session_id=session_id,
                    task_id=task_id,
                )
                if decision.verdict == "approved":
                    self.notifier(f"approved {approval_id}")
                    return decision
                return self._denied(
                    f"approval {approval_id} could not be bound to the "
                    f"current action ({decision.reason}); failing closed"
                )
            if record.status == "denied":
                return self._denied("operator denied the approval")
            if record.status == "consumed":
                # consume() atomically flips status to "consumed" and stamps
                # consumed_at; the old "approved" replay branch below is
                # dead for consumed records, so deny immediately instead of
                # silently polling until the wait window elapses.
                return self._denied("approval already consumed; replay denied")
            if record.status == "approved":
                # Unconsumed approval that was observed after the check
                # above -- only reachable in a race between get() and the
                # operator's consume(). Fail closed either way.
                return self._denied("approval already consumed; replay denied")
            # pending: keep waiting until the bounded deadline.
            if time.monotonic() >= deadline:
                return self._denied("approval not granted within the wait window")
            time.sleep(_POLL_INTERVAL_SECONDS)

    # -- post-action -------------------------------------------------------

    def inspect_result(self, tool_name: str = "", args: Any = None,
                       result: Any = None) -> Optional[str]:
        """Run post-action guards over a tool result.

        Returns:

        * ``None``               -- result unchanged (or not a string);
        * a string               -- redacted/transformed result the model
                                    should see instead;
        * the suppression marker -- the result must not reach the model at
                                    all (post-action deny or guard failure).
        """
        if not isinstance(result, str):
            return None
        ctx = ActionContext(
            skill=str(tool_name),
            args=dict(args) if isinstance(args, dict) else {},
            description=f"Hermes {tool_name} result",
            output=result,
        )
        try:
            outcome = self._pipeline.run_post(ctx)
        except Exception as exc:  # pragma: no cover - exact exception is irrelevant
            self.notifier(f"output suppressed — post-action guard failed: {exc}")
            return _SUPPRESSED
        if not outcome.allowed:
            reasons = "; ".join(v.reason for v in outcome.denials if v.reason)
            self.notifier(f"output suppressed — post-action deny: {reasons}")
            return _SUPPRESSED
        if ctx.output != result:
            return ctx.output
        return None

    # -- helpers -----------------------------------------------------------

    def _denied(self, reason: str) -> HermesDecision:
        self.notifier(f"denied: {reason}")
        return HermesDecision(
            verdict="denied", allowed=False, action_kind="unknown",
            reason=reason,
            notification=f"[hermes-guard] {reason}",
        )


def _bounded_wait(raw: str) -> float:
    """Clamp an approval wait value into the allowed window."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 300.0
    return max(_MIN_WAIT_SECONDS, min(_MAX_WAIT_SECONDS, value))
