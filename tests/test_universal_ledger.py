"""custodian.universal_ledger -- hash-chain integrity, tamper detection,
sanitization boundary, and concurrent-writer safety.

The concurrency test is the one that matters most: paladin.audit.AuditLog's
own docstring admits it only serializes appends *within one process*
(threading.Lock) and documents cross-process racing as a known, separate
gap. This module's whole design point is closing that gap by using a
SQLite BEGIN IMMEDIATE transaction instead of a Python lock -- so the test
suite has to actually prove concurrent writers don't fork or lose the
chain, not just assert it in a docstring.
"""
from __future__ import annotations

import multiprocessing
import threading

import pytest

from custodian.universal_ledger import (
    GENESIS_FALLBACK,
    LedgerChainBrokenError,
    LedgerEvent,
    LedgerValidationError,
    UniversalLedger,
)


def _event(**kw) -> LedgerEvent:
    base = dict(
        correlation_id="corr-1", requester="skill:stripe-spend",
        provider="custodian", action="stripe-spend", lifecycle_event="proposed",
    )
    base.update(kw)
    return LedgerEvent(**base)


def _mp_worker(i: int, path_str: str, per_proc: int) -> None:
    """Module-level (not a closure) so the spawn context can pickle it."""
    w = UniversalLedger(path_str)
    for j in range(per_proc):
        w.append(LedgerEvent(
            correlation_id=f"p{i}-{j}", requester="skill:stripe-spend",
            provider="custodian", action="stripe-spend",
            lifecycle_event="proposed", metadata={"proc": i, "seq": j},
        ))


@pytest.fixture
def ledger(tmp_path):
    return UniversalLedger(tmp_path / "ledger.db")


class TestAppendAndChain:
    def test_first_event_chains_from_genesis(self, ledger):
        digest = ledger.append(_event())
        row = ledger.tail(1)[0]
        assert row["prev_digest"] == ledger.genesis
        assert row["digest"] == digest

    def test_second_event_chains_from_first(self, ledger):
        d1 = ledger.append(_event(lifecycle_event="proposed"))
        d2 = ledger.append(_event(lifecycle_event="decided", verdict="autonomous"))
        rows = ledger.tail(2)
        assert rows[0]["prev_digest"] == d1  # most recent first
        assert rows[1]["prev_digest"] == ledger.genesis

    def test_genesis_is_installation_specific_not_a_fixed_literal(self, tmp_path):
        """GENESIS used to be a fixed "0"*64 literal -- every ledger
        anywhere started from the identical value, so nothing tied a
        chain to a specific installation, contradicting
        MODULAR_PLATFORM_HANDOVER.md's explicit "origin-bound genesis"
        requirement. Found in review."""
        a = UniversalLedger(tmp_path / "a.db")
        b = UniversalLedger(tmp_path / "b.db")
        assert a.genesis != b.genesis
        assert a.genesis != GENESIS_FALLBACK
        assert len(a.genesis) == 64

    def test_genesis_is_stable_across_reopens(self, tmp_path):
        path = tmp_path / "reopen.db"
        first = UniversalLedger(path)
        second = UniversalLedger(path)
        assert first.genesis == second.genesis

    def test_verify_passes_on_untouched_chain(self, ledger):
        for i in range(20):
            ledger.append(_event(lifecycle_event="proposed", metadata={"n": i}))
        ledger.verify()  # must not raise

    def test_verify_empty_ledger_is_fine(self, ledger):
        ledger.verify()


class TestTamperDetection:
    def test_editing_a_field_breaks_verification(self, ledger, tmp_path):
        ledger.append(_event())
        ledger.append(_event(lifecycle_event="decided", verdict="autonomous"))
        conn = ledger._connect()
        conn.execute("UPDATE ledger_events SET amount = 999999.0 WHERE id = 1")
        conn.commit()
        conn.close()
        with pytest.raises(LedgerChainBrokenError):
            ledger.verify()

    def test_deleting_a_row_breaks_verification(self, ledger):
        for i in range(5):
            ledger.append(_event(metadata={"n": i}))
        conn = ledger._connect()
        conn.execute("DELETE FROM ledger_events WHERE id = 3")
        conn.commit()
        conn.close()
        with pytest.raises(LedgerChainBrokenError):
            ledger.verify()

    def test_reordering_rows_breaks_verification(self, ledger):
        for i in range(3):
            ledger.append(_event(metadata={"n": i}))
        conn = ledger._connect()
        # Swap the digest/prev_digest of rows 1 and 2 to simulate reordering
        r1 = conn.execute("SELECT digest, prev_digest FROM ledger_events WHERE id=1").fetchone()
        r2 = conn.execute("SELECT digest, prev_digest FROM ledger_events WHERE id=2").fetchone()
        conn.execute("UPDATE ledger_events SET digest=?, prev_digest=? WHERE id=1", (r2[0], r2[1]))
        conn.execute("UPDATE ledger_events SET digest=?, prev_digest=? WHERE id=2", (r1[0], r1[1]))
        conn.commit()
        conn.close()
        with pytest.raises(LedgerChainBrokenError):
            ledger.verify()

    def test_a_forged_digest_is_caught(self, ledger):
        ledger.append(_event())
        conn = ledger._connect()
        conn.execute("UPDATE ledger_events SET digest = 'f' * 64 WHERE id = 1")
        conn.commit()
        conn.close()
        with pytest.raises(LedgerChainBrokenError):
            ledger.verify()


class TestSanitizationBoundary:
    def test_unknown_lifecycle_event_rejected(self, ledger):
        with pytest.raises(LedgerValidationError):
            ledger.append(_event(lifecycle_event="made_up_stage"))

    @pytest.mark.parametrize("field_name", [
        "external_id", "approver", "band", "currency", "destination_host", "receipt_ref",
    ])
    def test_oversized_value_rejected_in_every_bounded_field(self, ledger, field_name):
        """Only metadata had a size bound before -- external_id, approver,
        band, currency, destination_host, and receipt_ref had none at
        all, so a 500KB string passed validation and was written to disk
        verbatim. Found in review."""
        with pytest.raises(LedgerValidationError, match="chars, max"):
            ledger.append(_event(**{field_name: "x" * 100_000}))

    @pytest.mark.parametrize("field_name", [
        "external_id", "approver", "destination_host", "receipt_ref",
    ])
    def test_credential_shaped_value_rejected_in_every_bounded_field(self, ledger, field_name):
        """metadata was type/size checked but never content-scanned for
        secret shapes, despite the module's own docstring promising
        metadata is 'never a credential value' -- a real Stripe-key-shaped
        string passed validation and was written to disk verbatim in any
        of these fields. Found in review. (band/currency excluded here:
        their length bounds are tight enough -- 16 and 8 chars -- that no
        realistic secret shape fits regardless of content scanning.)"""
        with pytest.raises(LedgerValidationError, match="looks like a credential"):
            ledger.append(_event(**{field_name: "sk_live_51AbCdEfGhIjKlMnOpQrSt"}))

    def test_metadata_value_content_scanned_for_secret_shapes(self, ledger):
        with pytest.raises(LedgerValidationError, match="looks like a credential"):
            ledger.append(_event(metadata={"note": "AKIAABCDEFGHIJKLMNOP"}))

    def test_unknown_verdict_rejected(self, ledger):
        with pytest.raises(LedgerValidationError):
            ledger.append(_event(verdict="probably_fine"))

    def test_credential_refs_must_be_paladin_uris(self, ledger):
        with pytest.raises(LedgerValidationError, match="never a resolved value"):
            ledger.append(_event(credential_refs=("sk_live_actualsecretvalue123",)))

    def test_valid_credential_ref_is_accepted(self, ledger):
        ledger.append(_event(credential_refs=("paladin://stripe_sk",)))
        row = ledger.tail(1)[0]
        assert row["credential_refs"] == ["paladin://stripe_sk"]

    def test_metadata_rejects_nested_structures(self, ledger):
        with pytest.raises(LedgerValidationError, match="not a primitive"):
            ledger.append(_event(metadata={"nested": {"a": 1}}))

    def test_metadata_rejects_raw_args_shape(self, ledger):
        """The API boundary itself prevents 'just dump the tool args in
        here' -- a dict with a list value (the common shape of a raw
        args/prompt payload) is rejected, not merely discouraged."""
        with pytest.raises(LedgerValidationError):
            ledger.append(_event(metadata={"args": ["--amount", "5.00"]}))

    def test_metadata_size_bound_enforced(self, ledger):
        huge = {f"k{i}": "x" * 200 for i in range(30)}
        with pytest.raises(LedgerValidationError, match="bytes"):
            ledger.append(_event(metadata=huge))

    def test_metadata_key_count_bound_enforced(self, ledger):
        too_many = {f"k{i}": i for i in range(40)}
        with pytest.raises(LedgerValidationError, match="keys"):
            ledger.append(_event(metadata=too_many))

    def test_rejected_record_never_touches_the_chain(self, ledger):
        """Validation happens before the write transaction opens -- a
        bad record must not consume a chain link or leave any trace."""
        try:
            ledger.append(_event(lifecycle_event="not_real"))
        except LedgerValidationError:
            pass
        assert ledger.tail(10) == []


class TestQueries:
    def test_by_correlation_id_returns_full_lifecycle(self, ledger):
        ledger.append(_event(correlation_id="c1", lifecycle_event="proposed"))
        ledger.append(_event(correlation_id="c1", lifecycle_event="decided", verdict="autonomous"))
        ledger.append(_event(correlation_id="c2", lifecycle_event="proposed"))
        rows = ledger.by_correlation_id("c1")
        assert len(rows) == 2
        assert {r["lifecycle_event"] for r in rows} == {"proposed", "decided"}

    def test_by_external_id(self, ledger):
        ledger.append(_event(external_id="pi_abc123"))
        ledger.append(_event(external_id="pi_other"))
        rows = ledger.by_external_id("pi_abc123")
        assert len(rows) == 1 and rows[0]["external_id"] == "pi_abc123"

    def test_by_verdict(self, ledger):
        ledger.append(_event(lifecycle_event="decided", verdict="denied"))
        ledger.append(_event(lifecycle_event="decided", verdict="autonomous"))
        rows = ledger.by_verdict("denied")
        assert len(rows) == 1

    def test_in_time_range(self, ledger):
        ledger.append(_event(ts=100.0))
        ledger.append(_event(ts=200.0))
        ledger.append(_event(ts=300.0))
        rows = ledger.in_time_range(150.0, 250.0)
        assert len(rows) == 1 and rows[0]["ts"] == 200.0

    def test_tail_respects_limit_and_order(self, ledger):
        for i in range(5):
            ledger.append(_event(metadata={"n": i}))
        rows = ledger.tail(2)
        assert len(rows) == 2
        assert rows[0]["metadata"]["n"] == 4  # most recent first


class TestConcurrency:
    def test_concurrent_threads_do_not_fork_or_lose_the_chain(self, tmp_path):
        path = tmp_path / "concurrent.db"
        ledger = UniversalLedger(path)
        n_threads = 8
        per_thread = 15
        errors = []

        def worker(i):
            try:
                w = UniversalLedger(path)
                for j in range(per_thread):
                    w.append(_event(
                        correlation_id=f"t{i}-{j}",
                        metadata={"thread": i, "seq": j},
                    ))
            except Exception as e:  # pragma: no cover - failure path only
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"writer threads raised: {errors}"
        ledger.verify()  # the chain must still be a single, unbroken line
        rows = ledger.tail(10_000)
        assert len(rows) == n_threads * per_thread  # nothing silently lost

    def test_concurrent_processes_do_not_fork_or_lose_the_chain(self, tmp_path):
        """The real version of the claim: separate OS processes, not just
        threads in one interpreter. This is exactly the shape
        paladin.audit.AuditLog's threading.Lock cannot protect against."""
        path = tmp_path / "concurrent-mp.db"
        UniversalLedger(path)  # create schema before forking workers
        n_procs = 6
        per_proc = 10

        ctx = multiprocessing.get_context("spawn")
        procs = [
            ctx.Process(target=_mp_worker, args=(i, str(path), per_proc))
            for i in range(n_procs)
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=60)
            assert p.exitcode == 0, f"worker process failed (exitcode {p.exitcode})"

        ledger = UniversalLedger(path)
        ledger.verify()
        rows = ledger.tail(10_000)
        assert len(rows) == n_procs * per_proc
