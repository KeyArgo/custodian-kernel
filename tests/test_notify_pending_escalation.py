"""Tests for the operator-panel pending-escalation concurrency fix.

notify.py lives outside the installed package tree (it's a sandbox-only
script under skills/payments/stripe-spend/scripts/, imported by spend.py/
refund.py/approve.py at runtime inside the NemoClaw sandbox) so it's
loaded here via importlib rather than a normal package import.

Regression covered: PENDING_FILE/PENDING_CODE_FILE are single shared
paths per sandbox, not scoped per visitor/session. A second
write_pending() call used to silently overwrite a still-live first
escalation's record and code — surfacing to the first visitor as
approve.py's bare "No pending escalation found" when they entered a
code that really was valid a moment earlier. write_pending() now raises
PendingEscalationExistsError instead of clobbering.
"""
import importlib.util
import sys
import time
from pathlib import Path

import pytest

_NOTIFY_PATH = (
    Path(__file__).resolve().parent.parent
    / "skills" / "payments" / "stripe-spend" / "scripts" / "notify.py"
)


@pytest.fixture
def notify(tmp_path, monkeypatch):
    """Import notify.py fresh and redirect its state file paths into a
    tmp_path, so tests never touch the real skills/.../state directory."""
    spec = importlib.util.spec_from_file_location("notify_under_test", _NOTIFY_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["notify_under_test"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "PENDING_FILE", tmp_path / "pending_approval.json")
    monkeypatch.setattr(mod, "PENDING_CODE_FILE", tmp_path / "pending_code.json")
    yield mod
    del sys.modules["notify_under_test"]


def test_write_pending_succeeds_when_nothing_pending(notify):
    notify.write_pending(85.00, "cloud backup renewal", "over cap")
    assert notify.PENDING_FILE.exists()


def test_second_write_pending_refused_while_first_is_live(notify):
    notify.write_pending(85.00, "first request", "over cap")
    with pytest.raises(notify.PendingEscalationExistsError):
        notify.write_pending(3500.00, "second request", "over cap")
    # the first (still-live) record must survive untouched
    import json
    record = json.loads(notify.PENDING_FILE.read_text())
    assert record["description"] == "first request"


def test_write_pending_allowed_again_after_ttl_expires(notify, monkeypatch):
    notify.write_pending(85.00, "first request", "over cap")
    # simulate CODE_TTL having elapsed by rewriting created_at into the past
    import json
    record = json.loads(notify.PENDING_FILE.read_text())
    record["created_at"] = time.time() - notify.CODE_TTL - 1
    notify.PENDING_FILE.write_text(json.dumps(record))
    notify.write_pending(3500.00, "second request", "over cap")  # must not raise
    record2 = json.loads(notify.PENDING_FILE.read_text())
    assert record2["description"] == "second request"


def test_write_pending_allowed_after_corrupt_file(notify):
    notify.PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    notify.PENDING_FILE.write_text("{not valid json")
    notify.write_pending(85.00, "recovers from corruption", "over cap")  # must not raise
    import json
    assert json.loads(notify.PENDING_FILE.read_text())["description"] == "recovers from corruption"


def test_atomic_write_leaves_no_temp_file_behind(notify, tmp_path):
    notify.write_pending(85.00, "desc", "reason")
    leftovers = [p for p in tmp_path.iterdir() if ".tmp." in p.name]
    assert leftovers == []
