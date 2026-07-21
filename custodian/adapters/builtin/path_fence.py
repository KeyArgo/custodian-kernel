"""PathFence — a denylist fence over files the agent must never touch.

Where ScopeFence is an *allowlist* ("you may only work inside this
workspace"), PathFence is a *denylist* ("these specific paths are off
limits, work anywhere else"). It applies to BOTH reads and writes — a
model that was told not to read ``~/.ssh`` must be stopped from reading
it, not just writing to it — which is the case ScopeFence and
KernelSelfProtection (write-only) don't cover.

This is the adapter behind "keep the agent out of these folders" and
"don't let it read my keys." Matched paths are denied with a message
naming the rule, and (when a denial-log observer is wired) the attempt
is recorded — the user's explicit "log what it tried to do that it
wasn't allowed."

Config (all optional):
    forbidden_paths  — deny any read/write resolving under one of these
                       absolute prefixes (``~`` expanded; ``..`` collapsed;
                       symlinks followed to their real target)
    forbidden_globs  — deny any path whose resolved form OR basename
                       matches one of these fnmatch patterns (``*.env``,
                       ``id_*``, ``*.pem``)
    allow_paths      — optional allowlist: if set, deny anything NOT under
                       one of these (workspace confinement, like ScopeFence
                       but on this same read+write surface)
    read_tools /     — override the tool→direction map for non-Hermes
    write_tools        callers (defaults cover Hermes' real tool names)

Traversal AND symlinks are resolved before matching (shared
``_paths.resolve``), so neither ``/safe/../../.ssh/id_rsa`` nor a symlink
planted inside a safe directory that points at a forbidden one can slip
past a rule.

Shell commands get two independent checks, because a fixed verb
allowlist (``cat``, ``tee``, ...) can never enumerate every program
capable of touching a file — ``python3 -c "open(...)"``, ``base64``,
``vim``, ``openssl`` all read/write without any "file" verb in sight:

1. every non-flag token is tokenized and checked as a path candidate
   (closes bare commands like ``cat id_rsa`` and ``base64 /path``);
2. the raw, untokenized command text is substring-matched against every
   forbidden path (closes a forbidden path embedded inside a larger
   string — ``python3 -c "open('/home/u/.ssh/id_rsa')"``, ``source ~/.env``).
"""
from __future__ import annotations

import fnmatch
import os
import re
import shlex

from custodian.adapters.base import ActionContext, Adapter, Verdict
from custodian.adapters.builtin._paths import (
    PATH_ARG_HINT,
    looks_like_path,
    path_values,
    resolve,
    under_prefix,
)

# Real Hermes tool names (verified against the running agent), plus the
# generic names other callers use. Both directions matter for a denylist.
_DEFAULT_READ_TOOLS = frozenset({"read_file", "file-read", "cat", "view"})
_DEFAULT_WRITE_TOOLS = frozenset({
    "write_file", "patch", "file-write", "file-delete", "file-move", "edit_file",
})
_SHELL_TOOLS = frozenset({"shell", "bash", "terminal", "shell-exec"})

# Loose fallback for _relevant(): a tool name outside the exact sets above
# but still shaped like a file/exec operation should still get scanned —
# defense in depth against tool-name renames/aliases/third-party tools,
# mirroring kernel_self_protection.py's own _WRITE_HINT approach.
_TOOL_NAME_HINT = re.compile(
    r"(read|write|file|edit|patch|delete|move|shell|exec|terminal|bash)", re.I)

# A unified-diff hunk's target-file marker ("+++ b/path" / "--- a/path") —
# patch/diff-shaped tools carry the real target path INSIDE the diff body,
# under an arg key ("diff", "patch") that PATH_ARG_HINT never matches.
_DIFF_TARGET_RE = re.compile(r"^[+-]{3} [ab]/(.+)$", re.MULTILINE)


class PathFence(Adapter):
    """Denies reads and writes touching forbidden filesystem paths."""

    name = "path-fence"
    category = "security"
    fail_closed = True

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        # Optional caller working directory for resolving relative paths.
        # Defaulting to process cwd preserves the existing public behavior;
        # integrations such as Codex Guard set this explicitly because an MCP
        # server's cwd need not be the workspace it is governing.
        raw_base = self.config.get("base_path")
        self.base_path = resolve(raw_base) if raw_base else None
        raw_forbidden = list(self.config.get("forbidden_paths", []))
        self._forbidden_paths_raw = list(raw_forbidden)  # literal, un-resolved
        self.forbidden_paths = [resolve(p) for p in raw_forbidden]
        self.forbidden_globs = list(self.config.get("forbidden_globs", []))
        allow = self.config.get("allow_paths", [])
        self.allow_paths = [resolve(p) for p in allow] if allow else []
        self.read_tools = frozenset(self.config.get("read_tools", _DEFAULT_READ_TOOLS))
        self.write_tools = frozenset(self.config.get("write_tools", _DEFAULT_WRITE_TOOLS))

    def _resolve_candidate(self, raw: str) -> str:
        if self.base_path and not os.path.isabs(os.path.expanduser(raw)):
            return resolve(os.path.join(self.base_path, raw))
        return resolve(raw)

    # -- matching --------------------------------------------------------------

    def _forbidden(self, resolved: str) -> str | None:
        """Return a human reason if `resolved` is off-limits, else None."""
        if under_prefix(resolved, self.forbidden_paths):
            return f"path {resolved!r} is inside a forbidden location"
        for g in self.forbidden_globs:
            if fnmatch.fnmatchcase(resolved, g) or fnmatch.fnmatchcase(os.path.basename(resolved), g):
                return f"path {resolved!r} matches forbidden pattern {g!r}"
        if self.allow_paths and not under_prefix(resolved, self.allow_paths):
            return f"path {resolved!r} is outside the allowed workspace {self.allow_paths}"
        return None

    def _shell_text_hits_forbidden(self, command: str) -> str | None:
        """Catch a forbidden path referenced inside a larger string that
        the tokenizer wouldn't isolate as its own path-shaped token — an
        embedded one-liner (``python3 -c "open('/home/u/.ssh/id_rsa')"``)
        or a sourced literal (``source ~/.env``). Checked in both the raw
        (as configured, e.g. ``~/.ssh``) and resolved (``/home/u/.ssh``)
        forms, since a script may reference either.

        The match is right-boundary-bounded (must be followed by ``/``, a
        quote, whitespace, or end-of-string) so a longer, unrelated path
        that merely starts with the same characters (``~/.ssh-backup``)
        isn't a false positive — found in adversarial review."""
        if not command:
            return None
        for raw_prefix, resolved_prefix in zip(self._forbidden_paths_raw, self.forbidden_paths):
            if raw_prefix and re.search(re.escape(raw_prefix) + r'(?:[/"\'\s]|$)', command):
                return f"command references forbidden path {raw_prefix!r}"
            if re.search(re.escape(resolved_prefix) + r'(?:[/"\'\s]|$)', command):
                return f"command references forbidden path {resolved_prefix!r}"
        return None

    def _shell_component_hits_forbidden(self, command: str) -> str | None:
        """Catch a forbidden path's own directory/file component appearing
        as a bounded fragment even when the rest of the path is assembled
        dynamically — a shell variable or command substitution
        (``/home/$USER/.ssh/id_rsa``, ``cat /home/$(whoami)/.ssh/id_rsa``)
        or a literal split across separate string arguments in embedded
        code (``os.path.join(os.path.expanduser("~"), ".ssh", "id_rsa")``).
        Neither the exact-resolve check nor ``_shell_text_hits_forbidden``
        catches these: the full path never appears as one contiguous,
        resolvable substring — found in adversarial review.

        A component must be flanked by ``/``, a quote character, or
        start/end of string on BOTH sides (not a bare substring match),
        so an unrelated path that merely starts with the same characters
        (``~/.ssh-backup/file``) is not a false positive — the trailing
        ``-backup`` breaks the right-hand boundary."""
        if not command:
            return None
        seen: set[str] = set()
        for resolved_prefix in self.forbidden_paths:
            component = os.path.basename(resolved_prefix.rstrip(os.sep))
            if not component or len(component) < 3 or component in seen:
                continue
            seen.add(component)
            pattern = re.compile(r'(?:^|[/"\'])' + re.escape(component) + r'(?:[/"\']|$)')
            if pattern.search(command):
                return (f"command references forbidden path component {component!r} "
                        f"— possibly reached via a shell variable, command "
                        f"substitution, or a literal split across separate "
                        f"string arguments")
        return None

    def _candidate_paths(self, ctx: ActionContext) -> list[str]:
        """Every path-shaped value this tool call would touch."""
        out: list[str] = []
        # Direct path arguments (read_file/write_file: path, file_path).
        # path_values recurses into lists/dicts: {"paths": ["~/.ssh/id_rsa"]}
        # is an ordinary JSON tool-call shape, and the previous
        # isinstance(value, str) skip meant it was never checked at all.
        out.extend(path_values(ctx.args))
        # patch/diff-shaped tools: the real target lives inside the diff
        # body under a key ("diff", "patch") PATH_ARG_HINT never matches.
        if ctx.skill in ("patch", "edit_file"):
            for value in ctx.args.values():
                if isinstance(value, str):
                    out.extend(_DIFF_TARGET_RE.findall(value))
        # Shell commands: tokenize and check every non-flag argument as a
        # path candidate — NOT gated on a read/write verb matching first.
        # A fixed verb list can never cover every program capable of
        # touching a file (python3 -c, node -e, vim, openssl, base64, ...),
        # so the only safe default is to always scan.
        if ctx.skill in _SHELL_TOOLS:
            command = str(ctx.args.get("command", ctx.args.get("cmd", "")))
            if command:
                try:
                    tokens = shlex.split(command)
                except ValueError:
                    tokens = command.split()
                for tok in tokens[1:]:  # skip the binary/command name itself
                    if tok.startswith("-"):
                        continue  # a flag, not a path candidate
                    if looks_like_path(tok):
                        out.append(tok)
        return out

    def _relevant(self, ctx: ActionContext) -> bool:
        return (ctx.skill in self.read_tools
                or ctx.skill in self.write_tools
                or ctx.skill in _SHELL_TOOLS
                or bool(_TOOL_NAME_HINT.search(ctx.skill or "")))

    def pre_action(self, ctx: ActionContext) -> Verdict:
        if not (self.forbidden_paths or self.forbidden_globs or self.allow_paths):
            return Verdict.allow(self.name)  # nothing configured
        if not self._relevant(ctx):
            return Verdict.allow(self.name)

        if ctx.skill in _SHELL_TOOLS:
            command = str(ctx.args.get("command", ctx.args.get("cmd", "")))
            reason = self._shell_text_hits_forbidden(command)
            if not reason:
                reason = self._shell_component_hits_forbidden(command)
            if reason:
                return Verdict.deny(
                    self.name,
                    f"{reason} — this location is off limits by policy. "
                    f"The agent may not read or write it.",
                )

        for raw in self._candidate_paths(ctx):
            reason = self._forbidden(self._resolve_candidate(raw))
            if reason:
                return Verdict.deny(
                    self.name,
                    f"{reason} — this location is off limits by policy. "
                    f"The agent may not read or write it.",
                )
        return Verdict.allow(self.name)
