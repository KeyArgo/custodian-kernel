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
    url_hosts      — URL args must point at one of these hosts
    arg_pins       — {arg_name: required_value} exact pins, e.g.
                     {"customer_id": "cus_123"}

Path checks normalize ``..`` and symlink-free traversal before matching,
so ``/tmp/refund-1234/../../etc/passwd`` does not pass the prefix test.
"""
from __future__ import annotations

import os
import re
from urllib.parse import urlparse

from custodian.adapters.base import ActionContext, Adapter, Verdict

_PATH_ARG_HINT = re.compile(r"(path|file|dir|dest|src|output|input)", re.I)
_URL_RE = re.compile(r"https?://[^\s\"'<>]+")


class ScopeFence(Adapter):
    """Denies actions reaching outside the declared task scope."""

    name = "scope-fence"
    category = "guardrail"
    fail_closed = True

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.path_prefixes = [os.path.normpath(p) for p in self.config.get("path_prefixes", [])]
        self.url_hosts = set(self.config.get("url_hosts", []))
        self.arg_pins: dict = dict(self.config.get("arg_pins", {}))

    def _scope_line(self) -> str:
        bits = []
        if self.path_prefixes:
            bits.append(f"paths under {self.path_prefixes}")
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

        # Filesystem containment for any path-shaped argument.
        if self.path_prefixes:
            for key, value in ctx.args.items():
                if not isinstance(value, str) or not _PATH_ARG_HINT.search(key):
                    continue
                if not (value.startswith("/") or value.startswith("./") or "/" in value):
                    continue
                resolved = os.path.normpath(os.path.join("/", value)
                                            if not os.path.isabs(value) else value)
                if not any(resolved == p or resolved.startswith(p + os.sep)
                           for p in self.path_prefixes):
                    return Verdict.deny(
                        self.name,
                        f"path {value!r} (resolves to {resolved!r}) is outside the "
                        f"task workspace. Task scope: {self._scope_line()}",
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
