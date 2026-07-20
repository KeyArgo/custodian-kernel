"""ScopeFence — a task-scoped fence around what the agent may touch.

Where ContextAnchor pins *session-level* invariants, ScopeFence pins the
*current task*: "you are refunding order #1234" means file writes under
``/tmp/refund-1234/``, Stripe calls about that customer, and nothing
else. When a drifting model reaches for something out of scope — a path
outside the workspace, a URL off the allowlist, a customer other than
the declared one — the fence denies with a message restating the scope,
which doubles as a re-anchor for the model.

Config (all optional — an unset fence allows everything of that kind):
    path_prefixes  — file args must resolve under one of these prefixes
    path_globs     — file args must additionally match one of these
                     fnmatch patterns (e.g. ``*.log``, ``/srv/**/*.csv``)
    url_hosts      — URL args must point at one of these hosts
    arg_pins       — {arg_name: required_value} exact pins, e.g.
                     {"customer_id": "cus_123"}

Path checks normalize ``..`` and symlink-free traversal before matching,
so ``/tmp/refund-1234/../../etc/passwd`` does not pass the prefix test.

Globs are an ergonomic layer on top of prefixes (restricting *which
kinds* of files inside the workspace), never a substitute for them —
containment comes only from the prefix check. Configuring ``path_globs``
without ``path_prefixes`` is refused at construction time (raises
``ValueError``): a glob alone matches by filename/extension anywhere on
the filesystem, which is not scope containment and would silently
contradict this class's own fail-closed promise.
"""
from __future__ import annotations

import fnmatch
import os
import re
from urllib.parse import urlparse

from custodian.adapters.base import ActionContext, Adapter, Verdict
from custodian.adapters.builtin._paths import path_values, resolve, under_prefix

# The path-arg hint lives in _paths.PATH_ARG_HINT (reached via path_values) so
# all three fences agree on what counts as a path argument. This module used to
# carry its own byte-identical copy.
_URL_RE = re.compile(r"https?://[^\s\"'<>]+")


class ScopeFence(Adapter):
    """Denies actions reaching outside the declared task scope."""

    name = "scope-fence"
    category = "guardrail"
    fail_closed = True

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.path_prefixes = [os.path.normpath(p) for p in self.config.get("path_prefixes", [])]
        self.path_globs = list(self.config.get("path_globs", []))
        if self.path_globs and not self.path_prefixes:
            raise ValueError(
                "ScopeFence: path_globs requires path_prefixes — a glob alone "
                "(e.g. '*.log') matches by filename anywhere on the filesystem, "
                "which is not containment. Pair it with path_prefixes to scope "
                "the glob to a workspace, or drop path_globs if you meant "
                "unrestricted file access."
            )
        self.url_hosts = set(self.config.get("url_hosts", []))
        self.arg_pins: dict = dict(self.config.get("arg_pins", {}))

    def _scope_line(self) -> str:
        bits = []
        if self.path_prefixes:
            bits.append(f"paths under {self.path_prefixes}")
        if self.path_globs:
            bits.append(f"matching {self.path_globs}")
        if self.url_hosts:
            bits.append(f"hosts {sorted(self.url_hosts)}")
        if self.arg_pins:
            bits.append(f"pinned args {self.arg_pins}")
        return "; ".join(bits) or "unrestricted"

    def pre_action(self, ctx: ActionContext) -> Verdict:
        # Exact argument pins (e.g. the one customer this task is about).
        for arg, required in self.arg_pins.items():
            if arg in ctx.args and str(ctx.args[arg]) != str(required):
                return Verdict.deny(
                    self.name,
                    f"argument {arg}={ctx.args[arg]!r} is outside the current task "
                    f"scope (this task is pinned to {arg}={required!r}). "
                    f"Task scope: {self._scope_line()}",
                )

        # Filesystem containment for any path-shaped argument. Every string
        # value under a path-hinted key is checked, including a bare
        # relative filename with no '/' at all (e.g. "secrets.db") — a
        # fail-closed fence must not have a shape of input that silently
        # skips the check entirely just because it doesn't look enough
        # like a path.
        if self.path_prefixes or self.path_globs:
            # path_values recurses into containers. The previous
            # `not isinstance(value, str): continue` meant {"path": ["/etc/passwd"]}
            # -- an ordinary JSON tool-call shape -- skipped the fence entirely,
            # which is exactly the "shape of input that silently skips the
            # check" this comment warns against.
            for value in path_values(ctx.args):
                # Was os.path.normpath-only, contradicting this module's own
                # docstring claim of "symlink-free traversal": a symlink
                # planted inside an allowed workspace and pointing outside
                # it (ln -s ~/.ssh /tmp/work/evil) normalized to a path
                # string still under the workspace prefix, so reading
                # /tmp/work/evil/id_rsa was allowed. _paths.resolve() is the
                # shared, symlink-following helper PathFence already uses
                # for exactly this reason. Found in review, reproduced live.
                resolved = resolve(value)
                if self.path_prefixes and not under_prefix(resolved, self.path_prefixes):
                    return Verdict.deny(
                        self.name,
                        f"path {value!r} (resolves to {resolved!r}) is outside the "
                        f"task workspace. Task scope: {self._scope_line()}",
                    )
                if self.path_globs and not any(
                        fnmatch.fnmatchcase(resolved, g)
                        or fnmatch.fnmatchcase(os.path.basename(resolved), g)
                        for g in self.path_globs):
                    return Verdict.deny(
                        self.name,
                        f"path {value!r} does not match any allowed pattern "
                        f"{self.path_globs}. Task scope: {self._scope_line()}",
                    )

        # URL containment for any URL appearing anywhere in the args.
        if self.url_hosts:
            for url in _URL_RE.findall(ctx.text_surface()):
                host = urlparse(url).hostname or ""
                if host not in self.url_hosts:
                    return Verdict.deny(
                        self.name,
                        f"URL host {host!r} is outside the task's allowed hosts. "
                        f"Task scope: {self._scope_line()}",
                    )

        return Verdict.allow(self.name)
