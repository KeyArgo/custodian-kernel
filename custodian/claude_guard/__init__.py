"""Shim for the pre-0.5.0 module path ``custodian.claude_guard``.

The Claude guard now lives at :mod:`custodian.guards.claude`; this package
aliases it so existing imports, ``python -m custodian.claude_guard.hook``
hook wiring, and console-script references keep working. New code should
import :mod:`custodian.guards.claude` directly.
"""
import sys as _sys

from custodian.guards import claude as _guard

_sys.modules[__name__] = _guard
