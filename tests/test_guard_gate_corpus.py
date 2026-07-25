"""The standing gate corpus -- the guard graded against itself, every build.

Two properties, both the honest core of "caught once -> permanent gate; it can
never silently return":

1. **Ratchet (monotonic safety).** Every frozen gate in
   `tests/corpus/guard_gates.jsonl` is replayed and the guard's verdict must be
   at least as strict as the gate's floor. A verdict may get *stricter* over
   time; it may never get *weaker*. So a bypass, once closed, cannot silently
   reopen -- the build fails the moment it does.

2. **Fresh hunt.** The hunter's adversarial generator is re-run here, so the
   guard is graded against the whole attack surface (not just the frozen
   snapshot) on every build. If any dangerous input escapes -- including one a
   future guard change lets through -- this fails loudly. Grow the corpus with
   `python scripts/harden_guard.py --freeze`.

The corpus grows automatically; the guard's decision logic does not rewrite
itself (a security boundary shouldn't). What improves itself is coverage.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from custodian.codex_guard import corpus

REPO = Path(__file__).resolve().parent.parent
CORPUS_PATH = REPO / "tests" / "corpus" / "guard_gates.jsonl"


@pytest.fixture
def project_ws(tmp_path):
    ws = tmp_path / "project"
    ws.mkdir()
    return str(ws)


def _load_hunter():
    """Load scripts/harden_guard.py (not an importable package) by path."""
    path = REPO / "scripts" / "harden_guard.py"
    spec = importlib.util.spec_from_file_location("harden_guard", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_corpus_is_nonempty_and_valid():
    entries = corpus.load_corpus(CORPUS_PATH)  # raises on any malformed entry
    assert entries, "the gate corpus is empty; run scripts/harden_guard.py --freeze"


def test_corpus_has_no_duplicate_gates():
    entries = corpus.load_corpus(CORPUS_PATH)
    sigs = list(corpus.iter_signatures(entries))
    dupes = {s for s in sigs if sigs.count(s) > 1}
    assert not dupes, f"duplicate gate signatures in corpus: {len(dupes)}"


def test_gates_frozen_at_declared_floor_not_observed_strictness():
    """Gates must encode the security invariant the generator declared, not the
    incidental observed verdict. Freezing observed strictness would lock policy
    nuance in as invariant: a legit future softening of a destructive command
    from `denied` to `escalation_required` (still caught) would then false-alarm.
    So most gates carry `escalation_required` ("not autonomous"); `denied` appears
    only where denial itself is the contract (inline raw secret, bogus workspace).
    """
    entries = corpus.load_corpus(CORPUS_PATH)
    denied = [e for e in entries if e["floor"] == "denied"]
    # Every denied-floor gate must be one whose contract really is denial.
    for e in denied:
        assert e.get("family") in {"credential-inline", "workspace-sanity"}, (
            f"a {e.get('family')!r} gate is frozen at 'denied' -- that locks "
            f"incidental strictness in as invariant; declare 'escalation_required' "
            f"unless denial itself is the contract: {e['arguments']!r}")


def _corpus_ids(entry):
    fam = entry.get("family", "?")
    arg = entry["arguments"].get("command", entry["arguments"])
    return f"{fam}:{str(arg)[:48]}"


@pytest.mark.parametrize("entry", corpus.load_corpus(CORPUS_PATH), ids=_corpus_ids)
def test_frozen_gate_still_holds(entry, project_ws):
    holds, verdict = corpus.check_entry(entry, project_workspace=project_ws)
    assert holds, (
        f"RATCHET BROKEN: a previously-closed case reopened. "
        f"floor={entry['floor']} but guard now returns {verdict!r} for "
        f"{entry['arguments']!r}. A fixed bypass must never get weaker.")


def test_fresh_hunt_finds_no_escapes(project_ws):
    """Re-run the generator; every manufactured attack must still be caught.
    This is the 'engine against itself on every build' property."""
    hunter = _load_hunter()
    escapes = []
    for cand in hunter.generate_candidates():
        holds, verdict = corpus.check_entry(cand, project_workspace=project_ws)
        if not holds:
            escapes.append((cand["family"], verdict, cand["arguments"]))
    assert not escapes, (
        "the guard let dangerous input(s) run autonomously:\n"
        + "\n".join(f"  [{f}] verdict={v} args={a}" for f, v, a in escapes)
        + "\nFix the classifier, then `python scripts/harden_guard.py --freeze`.")
