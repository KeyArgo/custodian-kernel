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
* any Caduceus home (``~/.caduceus`` — vault, audit chain),
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

_WRITE_SKILLS = {"file-write", "file-delete", "file-move", "shell-exec"}
_WRITE_HINT = re.compile(r"(write|delete|remove|move|append|edit|patch|chmod|chown)", re.I)
_PATH_HINT = re.compile(r"(path|file|dest|target|output)", re.I)
# shell-exec commands that can write through the fence
_SHELL_WRITE = re.compile(r"(>|>>|\btee\b|\bmv\b|\bcp\b|\brm\b|\bsed\s+-i|\bchmod\b|\btruncate\b)")


def _default_protected() -> list[str]:
    home = os.path.expanduser("~")
    return [
        os.path.join(home, ".custodian"),
        os.path.join(home, ".caduceus"),
        os.environ.get("CADUCEUS_HOME", os.path.join(home, ".caduceus")),
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
        resolved = os.path.normpath(os.path.abspath(os.path.expanduser(path)))
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

        # Direct path arguments.
        for key, value in ctx.args.items():
            if not isinstance(value, str):
                continue
            if _PATH_HINT.search(key) and self._is_protected(value):
                return self._deny(value)

        # shell-exec: any protected path co-occurring with a write operator.
        if ctx.skill == "shell-exec":
            command = str(ctx.args.get("command", ctx.args.get("cmd", "")))
            if _SHELL_WRITE.search(command):
                for token in re.split(r"[\s;|&]+", command):
                    tok = token.strip("'\"")
                    if tok and ("/" in tok or tok in self.protected) \
                            and self._is_protected(tok):
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
