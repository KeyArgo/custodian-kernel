"""KernelSelfProtection — the agent cannot modify what governs it.

The strongest move available to a misbehaving (or merely confused)
agent is to edit the enforcement layer itself: relax policy.yaml,
delete the kill switch file, add itself a grant, drop a new "skill"
into the skills tree, or patch an adapter. Every one of those turns
future enforcement off — so this adapter denies them *categorically*,
before band checks, regardless of scope config, with no override knob
an agent could reach.

Protected by default:

* the Custodian state dir (``~/.custodian`` — policy, authority,
  kill switch, adapter manifests),
* any Paladin home (``~/.paladin``, and the pre-rename ``~/.warden`` —
  vault, audit chain),
* the active skills trees (``skills/``, ``bundled_skills/``) — an agent
  authoring a new skill is an agent minting itself a new capability;
  skill drafts belong in the configured ``quarantine`` dir, where a
  human reviews and installs them,
* SOUL.md / policy.yaml / COORDINATION.md in the workspace,
* the adapter directory itself.

Write-shaped actions are recognized by skill name (file-write,
shell-exec, ...) and by argument inspection. Reads are allowed — the
agent may look at its policy; it may not hold the pen.
"""
from __future__ import annotations

import os
import re

from custodian.adapters.base import ActionContext, Adapter, Verdict
from custodian.adapters.builtin._paths import path_values, resolve as _resolve

_WRITE_SKILLS = {"file-write", "file-delete", "file-move", "shell-exec", "docker-exec"}
_WRITE_HINT = re.compile(r"(write|delete|remove|move|append|edit|patch|chmod|chown)", re.I)
# A unified-diff target marker. patch/edit_file carry the real target path
# INSIDE the diff body, under a key ("diff", "patch") that no path-arg hint
# matches — so a diff rewriting SOUL.md sailed through while the identical
# write via a "path" arg was denied. PathFence has caught this since it was
# written; this adapter had no equivalent.
_DIFF_TARGET_RE = re.compile(r"^[+-]{3} [ab]/(.+)$", re.MULTILINE)
_DIFF_SKILLS = ("patch", "edit_file")
# shell-exec commands that can write through the fence
_SHELL_WRITE = re.compile(r"(>|>>|\btee\b|\bmv\b|\bcp\b|\brm\b|\bsed\s+-i|\bchmod\b|\btruncate\b)")


def _default_protected() -> list[str]:
    home = os.path.expanduser("~")
    # `or` not a get() default: an env var set to "" normpaths to "." and
    # matches nothing, so an empty PALADIN_HOME would contribute a hole to the
    # protected list rather than a path.
    paladin_home = os.environ.get("PALADIN_HOME") or os.path.join(home, ".paladin")
    warden_home = os.environ.get("WARDEN_HOME") or os.path.join(home, ".warden")
    return [
        os.path.join(home, ".custodian"),
        os.path.join(home, ".paladin"),
        paladin_home,
        # The pre-rename home is protected unconditionally, not only when
        # PALADIN_HOME is unset. This list must cover wherever the vault
        # *actually* is, which is not always where this version would put it:
        # Vault.default_path() still resolves to ~/.warden when that is the
        # only vault on disk. Protecting just the new path would leave the
        # guard defending an empty directory while the real vault sat
        # unprotected next to it -- a fail-open in the one adapter whose job
        # is stopping the agent from editing what governs it.
        os.path.join(home, ".warden"),
        warden_home,
        "skills", "bundled_skills",
        "SOUL.md", "policy.yaml", "COORDINATION.md",
    ]


class KernelSelfProtection(Adapter):
    """Denies any write reaching the kernel's own control surfaces."""

    name = "kernel-self-protection"
    category = "security"
    fail_closed = True

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        extra = self.config.get("protected_paths", [])
        self.quarantine = self.config.get("quarantine", "")
        self.protected = [os.path.normpath(p) for p in (_default_protected() + list(extra))]

    def _is_protected(self, path: str) -> bool:
        # _paths.resolve, not abspath: it follows symlinks. abspath does not,
        # so a link (or a Windows junction) planted outside a protected dir but
        # pointing into one resolved to its own path string and matched
        # nothing -- writes to ~/.custodian/kill_switch, authority.json and
        # adapters.yaml all went through. This adapter is the categorical,
        # no-override backstop against the agent editing what governs it, and
        # it was the only path guard not following links; PathFence and
        # ScopeFence already route through _paths.resolve, whose docstring
        # says a traversal/symlink fix must apply to every guard at once.
        # (policy.yaml appeared safe only because its BASENAME matches a
        # relative protected entry below -- which masked the hole in testing.)
        resolved = _resolve(path)
        basename = os.path.basename(resolved)
        for p in self.protected:
            if os.path.isabs(p):
                if resolved == p or resolved.startswith(p + os.sep):
                    return True
            else:
                # Relative entries match anywhere in the path (skills trees,
                # workspace control files) — deliberately broad.
                parts = resolved.split(os.sep)
                if p in parts or basename == p:
                    return True
        if self.quarantine:
            q = os.path.normpath(os.path.abspath(self.quarantine))
            if resolved == q or resolved.startswith(q + os.sep):
                return False  # quarantine is the sanctioned place for drafts
        return False

    def pre_action(self, ctx: ActionContext) -> Verdict:
        writeish = (ctx.skill in _WRITE_SKILLS
                    or _WRITE_HINT.search(ctx.skill or ""))
        if not writeish:
            return Verdict.allow(self.name)

        # Direct path arguments, including ones nested in lists/dicts —
        # path_values recurses, so {"path": ["~/.custodian/policy.yaml"]} is no
        # longer invisible. It also uses the shared PATH_ARG_HINT, which is
        # wider than the hint this adapter used to carry (that one lacked
        # dir/src/input).
        for value in path_values(ctx.args):
            if self._is_protected(value):
                return self._deny(value)

        # patch/edit_file: the target lives inside the diff body.
        if ctx.skill in _DIFF_SKILLS:
            for raw in ctx.args.values():
                if not isinstance(raw, str):
                    continue
                for target in _DIFF_TARGET_RE.findall(raw):
                    if self._is_protected(target):
                        return self._deny(target)

        # shell-exec / docker-exec: any protected path co-occurring with a
        # write operator. docker-exec ("Run a command inside a running
        # Docker container", a real registered L2 tool) was missing from
        # _WRITE_SKILLS and never matched _WRITE_HINT ("exec"/"docker"
        # aren't in it), so this adapter never even looked at its command
        # -- a container with ~/.custodian or ~/.paladin bind-mounted got
        # zero protection, structurally the same risk shell-exec already
        # covers. Found in review.
        if ctx.skill in ("shell-exec", "docker-exec"):
            command = str(ctx.args.get("command", ctx.args.get("cmd", "")))
            if _SHELL_WRITE.search(command):
                for token in re.split(r"[\s;|&]+", command):
                    tok = token.strip("'\"")
                    # No "/" gate: it excluded native Windows paths
                    # (C:\Users\...\.custodian\policy.yaml contains no forward
                    # slash and is not a literal member of self.protected), so
                    # the check simply never ran for them. _is_protected is
                    # cheap and authoritative — just ask it about every token.
                    if tok and self._is_protected(tok):
                        return self._deny(tok)
        return Verdict.allow(self.name)

    def _deny(self, path: str) -> Verdict:
        hint = (f" Draft new skills under {self.quarantine!r} for human review."
                if self.quarantine else
                " Ask the operator to make this change if it is genuinely needed.")
        return Verdict.deny(
            self.name,
            f"{path!r} is part of the enforcement layer (policy, vault, kill "
            f"switch, skills tree, or adapters) — agents cannot modify what "
            f"governs them, at any band.{hint}",
        )
