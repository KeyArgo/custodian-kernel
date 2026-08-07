"""Shim for the pre-0.5.0 module path ``custodian.hermes_guard``.

The Hermes guard now lives at :mod:`custodian.guards.hermes`; this package
aliases it so existing imports, the Hermes plugin entry point, and console
scripts keep working. New code should import :mod:`custodian.guards.hermes`
directly.
"""
import sys as _sys

from custodian.guards import hermes as _guard

_sys.modules[__name__] = _guard
