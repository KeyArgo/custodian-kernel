"""Self-test runner for pack manifests (tests/case.json).

Each pack ships a YAML+JSON manifest (see case.json) that pins the
expected outcome for every corpus file.  This runner loads the manifest,
replays each corpus case through the triage engine, and asserts the
expected verdict/disposition.

Usage::

    python -m custodian.packs.test_runner [pack_name ...]
    python -m custodian.packs.test_runner  # runs all packs

Pattern: cyberware's per-perk self-tests (test/case.json), adapted to
the pack-level policy-as-code model.  The manifest is hashed alongside
the pack source so the kernel can verify the pack+tests have not
changed between audit and execution (tamper-snapshot).
"""
from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


@dataclass
class TestCase:
    id: str
    description: str
    corpus_file: str
    expected_kernel_verdict: str
    expected_adapt_disposition: str
    expected_final_action: str
    expected_contradiction_count: Optional[int] = None


@dataclass
class TestManifest:
    pack: str
    version: str
    cases: list[TestCase]


def _parse_manifest(path: Path) -> TestManifest:
    """Parse a case.json that contains YAML frontmatter (metadata) + JSON body (cases).

    The file is a single YAML document: comments at the top, then a keyed
    structure with ``pack``, ``version``, and ``cases`` (list).  Some
    entries include a ``code:`` assertion instead of corpus keys.
    """
    raw = path.read_text()
    data = yaml.safe_load(raw) if yaml is not None and "yaml" in globals() else {}

    cases_raw: list[dict] = []
    if isinstance(data, dict):
        cases_raw = data.get("cases", [])

    cases: list[TestCase] = []
    for c in cases_raw:
        # Skip pure-code assertions (e.g. ``code: assert PolicyPack.autonomous_dispositions is frozenset()``)
        if "code" in c and "corpus_file" not in c:
            continue
        cases.append(TestCase(
            id=c["id"],
            description=c["description"],
            corpus_file=c["corpus_file"],
            expected_kernel_verdict=c["expected_kernel_verdict"],
            expected_adapt_disposition=c["expected_adapt_disposition"],
            expected_final_action=c["expected_final_action"],
            expected_contradiction_count=c.get("expected_contradiction_count"),
        ))

    meta: dict[str, Any] = data if isinstance(data, dict) else {}
    return TestManifest(
        pack=meta.get("pack", "unknown"),
        version=meta.get("version", "0.0.0"),
        cases=cases,
    )


def run_pack_tests(pack_name: str, state_dir: Optional[str] = None) -> list[str]:
    """Run all self-tests for a pack. Returns list of failure messages."""
    from custodian.packs.registry import get_pack
    from custodian.packs.engine import triage
    from custodian.policy.schema import Policy, BandConfig, EscalationConfig
    from custodian.types import AuthorityState, Band

    # Find the manifest
    packs_dir = Path(__file__).resolve().parent
    manifest_path = (packs_dir / pack_name / "tests" / "case.json")

    if not manifest_path.exists():
        return [f"[SKIP] {pack_name}: no test manifest at {manifest_path}"]

    manifest = _parse_manifest(manifest_path)
    pack = get_pack(pack_name)

    # Load the kernel policy for this pack
    kernel_policy_path = (packs_dir / pack_name / "policy.yaml")
    kernel_policy = None
    if kernel_policy_path.exists():
        if yaml is not None and "yaml" in globals():
            kernel_policy = Policy.from_yaml(kernel_policy_path)
        else:
            kernel_policy = _minimal_policy_from_pack()

    state = AuthorityState(
        band=Band.L2,
        per_action_cap=100.0,
        session_cap=500.0,
    )

    failures = []
    corpus_dir = manifest_path.parent.parent / "corpus"

    for tc in manifest.cases:
        corpus_path = corpus_dir / tc.corpus_file

        if not corpus_path.exists():
            failures.append(
                f"[FAIL] {tc.id}: corpus file {tc.corpus_file} not found at {corpus_path}"
            )
            continue

        try:
            envelope_dict = json.loads(corpus_path.read_text())

            # Run through triage
            result = triage(
                pack=pack,
                envelope=_dict_to_envelope(envelope_dict),
                kernel_policy=kernel_policy or _minimal_policy_from_pack(),
                state=state,
            )

            # Check expected outcomes
            ok = True
            reasons = []

            if result.kernel_verdict != tc.expected_kernel_verdict:
                ok = False
                reasons.append(
                    f"kernel_verdict: expected {tc.expected_kernel_verdict}, "
                    f"got {result.kernel_verdict}"
                )

            if result.adapter_disposition != tc.expected_adapt_disposition:
                ok = False
                reasons.append(
                    f"adapter_disposition: expected {tc.expected_adapt_disposition}, "
                    f"got {result.adapter_disposition}"
                )

            if result.final_action != tc.expected_final_action:
                ok = False
                reasons.append(
                    f"final_action: expected {tc.expected_final_action}, "
                    f"got {result.final_action}"
                )

            if tc.expected_contradiction_count is not None:
                actual_cc = len(result.contradictions)
                if actual_cc != tc.expected_contradiction_count:
                    ok = False
                    reasons.append(
                        f"contradiction_count: expected {tc.expected_contradiction_count}, "
                        f"got {actual_cc}"
                    )

            if ok:
                log.info("[PASS] %s (%s)", tc.id, tc.description)
            else:
                failures.append(
                    f"[FAIL] {tc.id}: {', '.join(reasons)}"
                )

        except Exception as e:
            failures.append(f"[ERROR] {tc.id}: {e}")

    return failures


def _dict_to_envelope(d: dict):
    """Convert a dict to an Envelope — minimal adapter for corpus files."""
    from custodian.packs.base import Envelope, Claim, EvidenceSpan

    claims_dicts = d.get("claims", [])
    claims = [Claim.from_dict(c) for c in claims_dicts]

    clauses_dicts = d.get("policy_clauses_cited", [])
    clauses = [EvidenceSpan(**c) for c in clauses_dicts]

    return Envelope(
        case_id=d.get("case_id", ""),
        customer_id=d.get("customer_id", ""),
        order_id=d.get("order_id", ""),
        amount=float(d.get("amount", 0)),
        requested_action=d.get("requested_action", "noop"),
        claims=claims,
        policy_clauses_cited=clauses,
        recommended_disposition=d.get("recommended_disposition", "escalate_ambiguous"),
        confidence=float(d.get("confidence", 0)),
        agent_summary=d.get("agent_summary", ""),
    )


def _minimal_policy_from_pack():
    from custodian.policy.schema import Policy, BandConfig, EscalationConfig
    from custodian.types import Band

    bands = {
        Band(b): BandConfig(
            name=Band(b),
            max_spend=100.0 if b in ("L0", "L1") else 50.0,
            requires_approval=b in ("L2", "L3", "L4"),
        )
        for b in ("L0", "L1", "L2", "L3", "L4")
    }
    return Policy(
        version="1.0",
        default_band=Band.L2,
        bands=bands,
        rules=[],
        escalation=EscalationConfig(),
    )


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    packs = sys.argv[1:] if len(sys.argv) > 1 else ["refunds", "purchasing", "cloud"]
    all_failures = []

    for pack_name in packs:
        if pack_name not in ["refunds", "purchasing", "cloud"]:
            print(f"[SKIP] {pack_name}: not a known pack")
            continue

        print(f"\n{'='*60}")
        print(f"Running self-tests for pack: {pack_name}")
        print(f"{'='*60}")

        failures = run_pack_tests(pack_name)

        if failures:
            for f in failures:
                print(f)
            all_failures.extend(failures)
        else:
            print(f"All tests passed for {pack_name}")

    if all_failures:
        print(f"\n{len(all_failures)} test(s) FAILED")
        sys.exit(1)
    else:
        print("\nAll pack self-tests passed")
        sys.exit(0)


if __name__ == "__main__":
    main()
