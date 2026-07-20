"""Shared --version support for the custodian and paladin CLIs (and,
imported externally, the standalone talaria package's CLI too).

A plain `version=f"...{_pkg_version()}"` string is evaluated the moment
`add_argument()` runs — i.e. on every single invocation of the CLI, not
just `--version` — because argparse's built-in version action only
defers *printing*, not computing, the string. LazyVersionAction defers
the metadata lookup itself, so `custodian status`, `paladin list`, etc.
never pay for it.
"""
from __future__ import annotations

import argparse


def pkg_version(distribution: str = "custodian-kernel") -> str:
    try:
        from importlib.metadata import version
        return version(distribution)
    except Exception:
        return "unknown"


class LazyVersionAction(argparse.Action):
    """Like argparse's built-in 'version' action, but computes the
    version string only when --version is actually passed."""

    def __init__(self, option_strings, dest=argparse.SUPPRESS,
                 fmt: str = "%(prog)s {version}", distribution: str = "custodian-kernel",
                 help: str = "show program's version number and exit"):
        super().__init__(option_strings=option_strings, dest=dest,
                         nargs=0, help=help)
        self._fmt = fmt
        self._distribution = distribution

    def __call__(self, parser, namespace, values, option_string=None):
        text = self._fmt.replace("%(prog)s", parser.prog).format(
            version=pkg_version(self._distribution))
        print(text)
        parser.exit()
