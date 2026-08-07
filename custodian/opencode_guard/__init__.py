"""Shim for the pre-0.5.0 module path ``custodian.opencode_guard``.

The OpenCode guard now lives at :mod:`custodian.guards.opencode`; this
package aliases it so existing imports keep working. New code should import
:mod:`custodian.guards.opencode` directly.
"""
import sys as _sys

from custodian.guards import opencode as _guard

_sys.modules[__name__] = _guard
