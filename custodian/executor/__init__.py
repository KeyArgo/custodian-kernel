"""Delegated execution: a separate executor identity holds the only code
path that can actually run a governed skill script.

Everything in custodian/tools/registry.py's CustodianTool.invoke() today is
*cooperative*: the calling agent's own process computes the kernel's
decision and, if autonomous, calls subprocess.run() itself, in the same
process, with the same memory space. A fully compromised agent process
(a supply-chain hit on a dependency, an injection that achieves arbitrary
code execution) can bypass every check in that file simply by not calling
it -- nothing stops the agent's own process from shelling out directly.

This package is *delegated*: custodian.executor.client.ExecutorClient is a
thin socket client with no execution code of its own at all -- it can only
ask a separate OS process (custodian.executor.service, started
independently, e.g. via `custodian executor start`) to run something. That
separate process re-derives the kernel's decision itself from its own copy
of the policy/tool registry, never trusting the client's claims about a
tool's band or cost. For an escalated (human-approval-required) action, the
gap between "kernel says escalate" and "a human actually approved this
exact action" is closed by custodian.executor.capability -- a signed,
digest-bound, single-use, TTL-bound record, so an approval can be consumed
exactly once, only for the exact action it was issued for.
"""
