"""Mutation gate for the guard's security-critical decision logic.

Regression tests prove the guard makes the *right* call on known-bad inputs.
This gate proves something a coverage number cannot: that those decisions are
actually *load-bearing* -- that if you flipped a `deny` to an `allow`, an
`escalation_required` to `autonomous`, or knocked newline out of the
destructive-command separator, a concrete adversarial input would expose it.

For each mutation we:

1. Assert the exact target source still exists in the module. If a refactor
   moves or rewrites it, THIS gate fails loudly rather than silently passing on
   a mutation that no longer applies -- a mutation gate that quietly becomes a
   no-op is the worst kind, so we forbid it. (This is the "caught once ->
   permanent gate, can never silently return" property, applied to the gate
   itself.)
2. Load a one-edit-mutated copy of the module in-process.
3. Run a probe -- a concrete input encoding a security invariant -- against both
   the original and the mutant. The invariant must hold on the original
   (sanity: the probe is real) and must BREAK on the mutant (the mutant is
   killed: some real test input distinguishes safe from unsafe behavior).

A surviving mutant (mutant behaves identically to the original on the probe)
means the flipped line is inert or untested -- a hole in the security suite,
and a hard failure here.

Scope note: this is a *targeted* gate over the guard's enforcement invariants,
not exhaustive mutation coverage of the whole tree. It is meant to run on every
build (fast, deterministic, no external tool). For exhaustive exploration, a
tool like `mutmut` scoped to `custodian/*_guard/` can be run out of band.
"""
from __future__ import annotations

import importlib
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pytest

# A real, non-home project directory the guard accepts as a workspace (home and
# filesystem-root workspaces are rejected upstream by design).
_WS = str(Path(__file__).resolve().parent.parent / "custodian")


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    # hook.decide -> evaluate_guard_action writes receipts; keep them in tmp.
    monkeypatch.setenv("CUSTODIAN_CODEX_GUARD_STATE_DIR", str(tmp_path / "state"))


def _load_mutant(dotted: str, package: str, old: str, new: str) -> types.ModuleType:
    """Return a copy of `dotted` with the single `old`->`new` edit applied.

    Raises if `old` is absent (the mutation no longer targets live code) or
    appears more than once (an ambiguous edit that could mutate the wrong site).
    """
    mod = importlib.import_module(dotted)
    src = Path(mod.__file__).read_text(encoding="utf-8")
    occurrences = src.count(old)
    if occurrences == 0:
        raise AssertionError(
            f"mutation target vanished from {dotted}: {old!r}. The guard was "
            f"refactored; update this gate so the invariant stays covered.")
    if occurrences > 1:
        raise AssertionError(
            f"mutation target is ambiguous in {dotted} ({occurrences}x): {old!r}. "
            f"Make the target string unique so the edit hits the intended site.")
    mutant_src = src.replace(old, new, 1)
    module = types.ModuleType(dotted)
    module.__file__ = mod.__file__
    module.__package__ = package  # so the module's relative imports resolve
    exec(compile(mutant_src, mod.__file__, "exec"), module.__dict__)
    return module


@dataclass(frozen=True)
class Mutation:
    name: str            # what security property this covers
    dotted: str          # module to mutate
    package: str         # its package (for relative-import resolution)
    old: str             # exact source to replace (must be unique)
    new: str             # the sabotage
    probe: Callable[[types.ModuleType], Any]  # returns the decision under test
    safe: Any            # the value the ORIGINAL returns and the mutant must NOT


# --- probes ----------------------------------------------------------------

def _p_inferred(mod, tool, command):
    return mod._inferred_kind(tool, {"command": command})


def _p_verdict(mod, **kw):
    return mod.evaluate_action(workspace=_WS, **kw).verdict


def _codex_decide(mod, event):
    return mod.decide(event)[0]  # ('deny'|'defer', reason)


def _claude_decide(mod, event):
    return mod.decide(event)[0]  # ('allow'|'ask'|'deny', reason)


def _codex_event(**over):
    e = {"tool_name": "shell", "tool_input": {"command": "ls"},
         "cwd": _WS, "session_id": "s-1"}
    e.update(over)
    return e


def _claude_event(**over):
    e = {"tool_name": "Read", "tool_input": {"file_path": _WS + "/x.py"},
         "cwd": _WS, "session_id": "s-1"}
    e.update(over)
    return e


# --- the mutation table ----------------------------------------------------
# Each entry: mutate one security-critical line, then prove a concrete input
# distinguishes the mutant from the original.

MUTATIONS = [
    # guard.py -- destructive-command classification --------------------------
    Mutation(
        # The destructive fix added BOTH `\n\r` to the separator class AND re.M
        # (`^` per line) -- overlapping defenses. A command whose `rm` sits at a
        # line start is caught by either, so it can't isolate this edit. The one
        # case ONLY the character class covers is an INDENTED destructive command
        # after a newline: `^` (no trailing `\s*`) misses the leading whitespace,
        # so if `\n\r` leaves the class, `\n\s*rm` no longer matches. (This
        # distinction was surfaced by the gate itself -- the naive probe survived.)
        name="destructive separator drops newline -> indented multi-line rm slips through",
        dotted="custodian.codex_guard.guard", package="custodian.codex_guard",
        old=r"[;&|\n\r]\s*", new=r"[;&|]\s*",
        probe=lambda m: _p_inferred(m, "shell", "echo hi\n  rm -rf /tmp/x"),
        # ActionKind.DESTRUCTIVE on the original; None once newline stops matching.
        safe=importlib.import_module("custodian.codex_guard.guard").ActionKind.DESTRUCTIVE,
    ),
    # guard.py -- secret-named env var exposed to stdout must be caught -------
    Mutation(
        # The credential-exposure rule (found by scripts/harden_guard.py). Break
        # the SECRET keyword and `echo $STRIPE_SECRET_KEY` stops classifying as
        # a credential leak and runs autonomously.
        name="credential-exposure keyword removed -> echo $SECRET runs autonomously",
        dotted="custodian.codex_guard.guard", package="custodian.codex_guard",
        old="(?:SECRET|TOKEN|PASSWORD", new="(?:SECRETX|TOKEN|PASSWORD",
        probe=lambda m: _p_inferred(m, "shell", "echo $STRIPE_SECRET_KEY"),
        safe=importlib.import_module("custodian.codex_guard.guard").ActionKind.CREDENTIAL,
    ),
    # guard.py -- risk can be overstated, never understated -------------------
    Mutation(
        name="inferred-risk promotion inverted -> declared 'read' hides a git push",
        dotted="custodian.codex_guard.guard", package="custodian.codex_guard",
        old="effective_kind = inferred if inferred in _ESCALATE else kind",
        new="effective_kind = inferred if inferred not in _ESCALATE else kind",
        probe=lambda m: _p_verdict(m, tool="shell", action_kind="read",
                                   arguments={"command": "git push origin main"}),
        safe="escalation_required",
    ),
    # guard.py -- the escalation gate itself ----------------------------------
    Mutation(
        name="escalation branch inverted -> consequential actions run autonomously",
        dotted="custodian.codex_guard.guard", package="custodian.codex_guard",
        old="if effective_kind in _ESCALATE:",
        new="if effective_kind not in _ESCALATE:",
        probe=lambda m: _p_verdict(m, tool="git-push", action_kind="network",
                                   arguments={"remote": "origin"}),
        safe="escalation_required",
    ),
    # guard.py -- unknown action kind must fail closed ------------------------
    Mutation(
        name="unknown-kind fail-closed flipped to autonomous",
        dotted="custodian.codex_guard.guard", package="custodian.codex_guard",
        old='verdict="denied",\n            action_kind=str(action_kind),',
        new='verdict="autonomous",\n            action_kind=str(action_kind),',
        probe=lambda m: _p_verdict(m, tool="shell", action_kind="not-a-real-kind",
                                   arguments={"command": "ls"}),
        safe="denied",
    ),
    # guard.py -- a bogus workspace must fail closed --------------------------
    Mutation(
        name="workspace-sanity 'or' weakened to 'and' -> home-dir workspace allowed",
        dotted="custodian.codex_guard.guard", package="custodian.codex_guard",
        old="if resolved_workspace is None or _is_unreasonable_workspace_root(resolved_workspace):",
        new="if resolved_workspace is None and _is_unreasonable_workspace_root(resolved_workspace):",
        probe=lambda m: m.evaluate_action(
            tool="shell", action_kind="read", arguments={"command": "ls"},
            workspace=str(Path.home())).verdict,
        safe="denied",
    ),
    # codex hook.py -- deny must not become defer -----------------------------
    Mutation(
        name="codex hook: denied verdict downgraded to defer (fails open)",
        dotted="custodian.codex_guard.hook", package="custodian.codex_guard",
        old='if verdict == "denied":\n        return "deny", f"Custodian denied this action',
        new='if verdict == "denied":\n        return "defer", f"Custodian denied this action',
        probe=lambda m: _codex_decide(m, _codex_event(
            tool_name="shell", tool_input={"command": "rm -rf ~/"})),
        safe="deny",
    ),
    # codex hook.py -- malformed event must fail closed -----------------------
    Mutation(
        name="codex hook: missing-tool fail-closed downgraded to defer",
        dotted="custodian.codex_guard.hook", package="custodian.codex_guard",
        old='return "deny", "Custodian: missing tool name; failing closed"',
        new='return "defer", "Custodian: missing tool name; failing closed"',
        probe=lambda m: _codex_decide(m, _codex_event(tool_name=None)),
        safe="deny",
    ),
    # codex hook.py -- missing session_id must fail closed --------------------
    Mutation(
        name="codex hook: missing session_id fail-closed downgraded to defer",
        dotted="custodian.codex_guard.hook", package="custodian.codex_guard",
        old='return "deny", "Custodian: missing session_id; failing closed"',
        new='return "defer", "Custodian: missing session_id; failing closed"',
        probe=lambda m: _codex_decide(m, _codex_event(session_id=None)),
        safe="deny",
    ),
    # claude hook.py -- deny must not become allow ----------------------------
    Mutation(
        name="claude hook: denied verdict flipped to allow (fails open)",
        dotted="custodian.claude_guard.hook", package="custodian.claude_guard",
        old='if verdict == "denied":\n        return "deny", f"Custodian denied this action',
        new='if verdict == "denied":\n        return "allow", f"Custodian denied this action',
        probe=lambda m: _claude_decide(m, _claude_event(
            tool_name="Write",
            tool_input={"file_path": "~/.ssh/authorized_keys", "content": "k"})),
        safe="deny",
    ),
    # claude hook.py -- escalation must ask, not silently allow ---------------
    Mutation(
        name="claude hook: escalation_required flipped to allow",
        dotted="custodian.claude_guard.hook", package="custodian.claude_guard",
        old='if verdict == "escalation_required":\n        return "ask"',
        new='if verdict == "escalation_required":\n        return "allow"',
        probe=lambda m: _claude_decide(m, _claude_event(
            tool_name="WebFetch", tool_input={"url": "http://example"})),
        safe="ask",
    ),
    # claude hook.py -- malformed event must fail closed ----------------------
    Mutation(
        name="claude hook: missing-tool fail-closed flipped to allow",
        dotted="custodian.claude_guard.hook", package="custodian.claude_guard",
        old='return "deny", "Custodian: missing tool name; failing closed"',
        new='return "allow", "Custodian: missing tool name; failing closed"',
        probe=lambda m: _claude_decide(m, _claude_event(tool_name=None)),
        safe="deny",
    ),
]


@pytest.mark.parametrize("mut", MUTATIONS, ids=lambda m: m.name)
def test_security_mutant_is_killed(mut: Mutation):
    # 1. The invariant must genuinely hold on the real module: if this fails,
    #    the probe is wrong, not the guard.
    original = importlib.import_module(mut.dotted)
    assert mut.probe(original) == mut.safe, (
        f"probe does not hold on the ORIGINAL for {mut.name!r}: "
        f"expected {mut.safe!r}. Fix the probe.")

    # 2. Loading the mutant also asserts the target line still exists (unique),
    #    so this gate can never silently degrade into a no-op.
    mutant = _load_mutant(mut.dotted, mut.package, mut.old, mut.new)

    # 3. The mutant must be KILLED: the same input now yields an unsafe/different
    #    decision. If it still returns `safe`, the flipped line is untested.
    assert mut.probe(mutant) != mut.safe, (
        f"SURVIVING MUTANT: {mut.name!r}. Flipping this line did not change the "
        f"decision on the probe input -- the security invariant is not actually "
        f"enforced by a test. Add coverage before shipping.")


def test_every_mutation_targets_live_unique_code():
    """Fast structural check (independent of probe execution): every mutation's
    target string exists exactly once in its module. Guarantees the whole table
    is live even if a probe is skipped or a module import is slow."""
    stale = []
    for mut in MUTATIONS:
        mod = importlib.import_module(mut.dotted)
        n = Path(mod.__file__).read_text(encoding="utf-8").count(mut.old)
        if n != 1:
            stale.append(f"{mut.name}: found {n}x in {mut.dotted} (want 1)")
    assert not stale, "mutation gate has drifted from the code:\n" + "\n".join(stale)
