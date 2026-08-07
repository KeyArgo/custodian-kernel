"""Shim for the pre-0.5.0 module path ``custodian.codex_guard``.

The Codex guard now lives at :mod:`custodian.guards.codex`; this package
aliases it so existing imports, ``python -m custodian.codex_guard.hook``
hook wiring, and console-script references keep working. New code should
import :mod:`custodian.guards.codex` directly.
"""
import sys as _sys

from custodian.guards import codex as _guard

_sys.modules[__name__] = _guard
