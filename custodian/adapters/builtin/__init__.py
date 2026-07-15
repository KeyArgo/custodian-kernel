"""Built-in guard adapters, grouped by category.

money      — spend-sentinel
security   — prompt-injection-guard, secret-leak-guard,
             kernel-self-protection, path-fence, egress-domain-guard
privacy    — pii-redactor
guardrail  — context-anchor, repetition-breaker, tool-confabulation-guard,
             scope-fence

Each is importable directly and discoverable via
:func:`custodian.adapters.registry.builtin_adapters`.
"""
from custodian.adapters.builtin.spend_sentinel import SpendSentinel
from custodian.adapters.builtin.prompt_injection_guard import PromptInjectionGuard
from custodian.adapters.builtin.secret_leak_guard import SecretLeakGuard
from custodian.adapters.builtin.pii_redactor import PiiRedactor
from custodian.adapters.builtin.context_anchor import ContextAnchor
from custodian.adapters.builtin.repetition_breaker import RepetitionBreaker
from custodian.adapters.builtin.tool_confabulation_guard import ToolConfabulationGuard
from custodian.adapters.builtin.scope_fence import ScopeFence
from custodian.adapters.builtin.kernel_self_protection import KernelSelfProtection
from custodian.adapters.builtin.path_fence import PathFence
from custodian.adapters.builtin.egress_domain_guard import EgressDomainGuard

ALL_BUILTINS = [
    SpendSentinel,
    PromptInjectionGuard,
    SecretLeakGuard,
    PiiRedactor,
    ContextAnchor,
    RepetitionBreaker,
    ToolConfabulationGuard,
    ScopeFence,
    KernelSelfProtection,
    PathFence,
    EgressDomainGuard,
]

__all__ = [cls.__name__ for cls in ALL_BUILTINS] + ["ALL_BUILTINS"]
