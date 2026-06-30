"""Tests for custodian poison-tests command."""
from __future__ import annotations

import argparse

import pytest

from custodian.cli import cmd_poison_tests
from custodian.packs.base import Claim, ClaimStatus, verify_claims


def _ns() -> argparse.Namespace:
    return argparse.Namespace()


class TestPoisonCases:
    """The five planted poison cases must ALL be caught as CONTRADICTED."""

    def test_self_approval_contradicted(self):
        claims = [cmd_poison_tests._POISON_CASES[0]["claim"]]
        scope = cmd_poison_tests._POISON_CASES[0]["scope"]
        result = verify_claims(claims, scope)
        assert result[0].status == ClaimStatus.CONTRADICTED

    def test_phantom_revenue_contradicted(self):
        claims = [cmd_poison_tests._POISON_CASES[1]["claim"]]
        scope = cmd_poison_tests._POISON_CASES[1]["scope"]
        result = verify_claims(claims, scope)
        assert result[0].status == ClaimStatus.CONTRADICTED

    def test_duplicate_spend_contradicted(self):
        claims = [cmd_poison_tests._POISON_CASES[2]["claim"]]
        scope = cmd_poison_tests._POISON_CASES[2]["scope"]
        result = verify_claims(claims, scope)
        assert result[0].status == ClaimStatus.CONTRADICTED

    def test_off_band_escalation_contradicted(self):
        claims = [cmd_poison_tests._POISON_CASES[3]["claim"]]
        scope = cmd_poison_tests._POISON_CASES[3]["scope"]
        result = verify_claims(claims, scope)
        assert result[0].status == ClaimStatus.CONTRADICTED

    def test_fraudulent_refund_contradicted(self):
        claims = [cmd_poison_tests._POISON_CASES[4]["claim"]]
        scope = cmd_poison_tests._POISON_CASES[4]["scope"]
        result = verify_claims(claims, scope)
        assert result[0].status == ClaimStatus.CONTRADICTED


class TestPoisonTestsCLI:
    """Integration tests for the CLI run() entry point."""

    def test_run_prints_all_captured(self, capsys):
        rc = cmd_poison_tests.run(_ns())
        assert rc == 0
        out = capsys.readouterr().out
        assert "5 caught, 0 missed" in out
        assert "POISON TESTS" in out
        for case in cmd_poison_tests._POISON_CASES:
            assert f"✓ {case['name']}" in out

    def test_run_all_verdicts_are_contradicted(self, capsys):
        """Every single output line should show → CONTRADICTED."""
        rc = cmd_poison_tests.run(_ns())
        assert rc == 0
        out = capsys.readouterr().out
        assert "→ CONTRADICTED" in out
        assert "✗" not in out   # no red crosses — nothing slipped through
        assert "VERIFIER HOLE" not in out
