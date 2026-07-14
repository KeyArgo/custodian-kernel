"""Adapters — pluggable pieces around the kernel, in two families.

**Integration adapters** are how the kernel talks to a specific execution
environment (NemoClaw sandboxes today; other runtimes tomorrow).

**Guard adapters** are pre/post hooks around every governed action —
money, security, privacy, and guardrail checks that catch what a model
does *wrong inside* its authority (see ``base.py``). Built-ins live in
``builtin/``; third-party packs plug in via the ``custodian.adapters``
entry-point group; local files install hash-pinned via
``custodian adapters install``.

The kernel itself (govern.py, middleware.py, policy/) has no dependency on
anything in this package. Adapters are reusable glue a site wires in; they
don't become part of the kernel — and the two families don't depend on
each other either. NemoClaw is imported lazily below so this package
stays importable (and the guard-adapter framework fully usable) on a
checkout that doesn't have nemoclaw.py — everything here is opt-in,
pick-your-own-use-case, never a package-wide hard dependency.
"""
from custodian.adapters.base import (
    ActionContext,
    Adapter,
    Decision,
    Verdict,
)
from custodian.adapters.pipeline import AdapterPipeline, PipelineResult
from custodian.adapters.registry import AdapterRegistry, AdapterLoadError

__all__ = [
    "Adapter",
    "ActionContext",
    "Decision",
    "Verdict",
    "AdapterPipeline",
    "PipelineResult",
    "AdapterRegistry",
    "AdapterLoadError",
]

try:
    from custodian.adapters.nemoclaw import (  # noqa: F401
        ExecResult,
        NemoClawExecutor,
        SandboxHealth,
    )
    __all__ += ["NemoClawExecutor", "ExecResult", "SandboxHealth"]
except ImportError:
    pass  # NemoClaw integration adapter not present on this checkout
