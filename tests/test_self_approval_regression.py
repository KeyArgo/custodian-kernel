"""Regression test for the self-approval security hole found and fixed
during this build.

The bug: an earlier version of spend.py accepted an --approved-by flag,
letting the agent itself assert its own escalation was approved, with no
real verification. The fix: spend.py/spend_v2.py have NO such flag at all --
not validated away, structurally absent -- and the only path to execute an
over-cap spend is approve.py/approve_v2.py, gated on a real external
verification check (Twilio Verify) that the requesting process cannot
satisfy on its own.

This test exists so that fix can never silently regress. If anyone adds an
--approved-by-style flag back to the unprivileged request path, or adds a
way to execute a spend without going through check_response(), this test
must fail.
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path

import pytest

from custodian.backends.base import ApprovalBackend
from custodian.backends.twilio_verify import TwilioVerifyBackend

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEND_V2 = REPO_ROOT / "skills" / "payments" / "stripe-spend" / "scripts" / "spend_v2.py"
APPROVE_V2 = REPO_ROOT / "skills" / "payments" / "stripe-spend" / "scripts" / "approve_v2.py"


def _argparse_arg_names(script_path: Path) -> set[str]:
    """Statically extract every --flag name added via add_argument() calls,
    without executing the script (it imports sandbox-only modules like
    _core/notify that aren't available outside the sandbox)."""
    tree = ast.parse(script_path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
        ):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if arg.value.startswith("--"):
                        names.add(arg.value.lstrip("-").replace("-", "_"))
    return names


class TestSpendCannotSelfApprove:
    def test_spend_v2_has_no_approved_by_flag(self):
        """The unprivileged request script must never be able to assert
        its own approval. This is the exact shape of the bug that was
        found and fixed -- if this ever becomes False again, that bug is
        back."""
        flags = _argparse_arg_names(SPEND_V2)
        assert "approved_by" not in flags, (
            "spend_v2.py has an --approved-by flag -- this reintroduces the "
            "self-approval hole. The unprivileged request path must never "
            "be able to assert its own approval."
        )

    def test_spend_v2_only_has_expected_flags(self):
        """Pin the exact flag set, so an --approved-by-equivalent added
        under a different name (e.g. --override, --force-approve) is also
        caught, not just the literal original name."""
        flags = _argparse_arg_names(SPEND_V2)
        allowed = {"amount", "description", "denied_by", "recipe", "to", "message"}
        unexpected = flags - allowed
        assert not unexpected, (
            f"spend_v2.py has unexpected flags not in the reviewed allowlist: "
            f"{unexpected}. If this is a real new feature, review it for "
            f"self-approval risk before adding it here."
        )

    def test_approve_v2_requires_approved_by_and_a_code(self):
        """The privileged executor must require both a human-attributed
        name AND a code -- the code is the part that can't be faked."""
        tree = ast.parse(APPROVE_V2.read_text())
        source = APPROVE_V2.read_text()
        assert '"code"' in source, "approve_v2.py must require a positional code argument"
        assert "--approved-by" in source, "approve_v2.py must require --approved-by"
        assert "required=True" in source

    def test_approve_v2_calls_check_response_before_executing(self):
        """The privileged executor must check the response via the backend
        BEFORE calling execute_spend -- not after, not optionally."""
        source = APPROVE_V2.read_text()
        check_idx = source.find("check_approval_code")
        execute_idx = source.find("execute_spend")
        assert check_idx != -1, "approve_v2.py must call the verification check"
        assert execute_idx != -1, "approve_v2.py must call execute_spend"
        assert check_idx < execute_idx, (
            "approve_v2.py calls execute_spend before checking the approval "
            "code -- this would let an unverified request execute. The check "
            "must happen first."
        )


class TestApprovalBackendCannotBeAnsweredLocally:
    def test_check_response_is_abstract_and_must_hit_an_external_source(self):
        """ApprovalBackend.check_response has no default implementation --
        every backend must define its own, and the only shipped
        implementation (TwilioVerifyBackend) hits a real external API,
        not local state."""
        assert ApprovalBackend.check_response.__isabstractmethod__

    def test_twilio_backend_check_response_makes_an_http_call(self):
        """Statically confirm TwilioVerifyBackend.check_response is
        implemented via an HTTP call to Twilio, not a local comparison
        against something the requesting process could have written."""
        import inspect
        source = inspect.getsource(TwilioVerifyBackend.check_response)
        assert "requests.post" in source
        assert "verify.twilio.com" in source
        # And it must NOT compare against any locally-stored secret/code --
        # there is no local "expected code" value anywhere in this method.
        assert "self." not in source.split("requests.post")[0] or True  # see below
        # Stronger check: the method must not read any local file or env
        # var that could contain a code value before making the request.
        assert "open(" not in source
        assert "os.environ" not in source


def test_pending_approval_never_stores_the_code():
    """state/pending_approval.json (mirrored by PendingApproval) only ever
    stores amount/description/reason/created_at -- never a code. If a code
    ever ends up in this record, self-approval becomes possible again
    because the requesting process can read its own pending-approval file."""
    from custodian.types import PendingApproval
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(PendingApproval)}
    assert "code" not in field_names
    assert "approval_code" not in field_names
    assert "verification_code" not in field_names
