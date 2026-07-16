"""Denial log + pipeline observer tests."""
import sys

import pytest

from custodian.adapters.base import ActionContext, Adapter, Verdict
from custodian.adapters.pipeline import AdapterPipeline
from talaria.denial_log import DenialLog
from paladin.errors import AuditChainBrokenError


def ctx(skill, args=None, **kw):
    return ActionContext(skill=skill, args=args or {}, **kw)


class _Deny(Adapter):
    name = "test-deny"
    category = "security"
    def pre_action(self, c):
        return Verdict.deny(self.name, "blocked for testing")


class _Warn(Adapter):
    name = "test-warn"
    def pre_action(self, c):
        return Verdict.warn(self.name, "warned for testing")


# -- pipeline observer -------------------------------------------------------

def test_observer_fires_on_deny():
    seen = []
    pipe = AdapterPipeline([_Deny()], observer=lambda c, v: seen.append((c.skill, v.adapter)))
    pipe.run_pre(ctx("read_file"))
    assert seen == [("read_file", "test-deny")]


def test_observer_not_fired_on_allow():
    seen = []

    class _Allow(Adapter):
        name = "ok"
        def pre_action(self, c):
            return Verdict.allow(self.name)

    AdapterPipeline([_Allow()], observer=lambda c, v: seen.append(v)).run_pre(ctx("x"))
    assert seen == []


def test_observer_crash_does_not_break_enforcement():
    def boom(c, v):
        raise RuntimeError("observer blew up")
    pipe = AdapterPipeline([_Deny()], observer=boom)
    r = pipe.run_pre(ctx("x"))
    assert not r.allowed  # denial still stands despite observer crash


# -- denial log ---------------------------------------------------------------

def test_denial_log_records_and_verifies(tmp_path):
    log = DenialLog(dir_path=tmp_path)
    log.record("read_file", "path-fence", "path is forbidden")
    log.record("write_file", "secret-leak-guard", "credential in args")
    assert log.verify() == 2
    recs = log.records()
    assert recs[0]["ref"] == "read_file" and recs[0]["requester"] == "path-fence"
    assert recs[0]["event"] == "deny"


@pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "os.chmod on Windows only toggles the read-only bit and cannot express "
        "0600 — the mode is 0666 regardless. The HMAC key's at-rest protection "
        "on Windows is filesystem ACLs, not POSIX modes. Meaningful on POSIX; "
        "unsatisfiable here."
    ),
)
def test_denial_log_key_is_0600(tmp_path):
    import stat
    DenialLog(dir_path=tmp_path)
    mode = stat.S_IMODE((tmp_path / "denial.key").stat().st_mode)
    assert mode == 0o600


def test_denial_log_tamper_detected(tmp_path):
    log = DenialLog(dir_path=tmp_path)
    log.record("read_file", "path-fence", "forbidden")
    log.record("write_file", "path-fence", "forbidden too")
    # tamper with the first record's reason
    lines = log.path.read_text().splitlines()
    import json as _json
    d = _json.loads(lines[0]); d["detail"] = "totally fine actually"
    lines[0] = _json.dumps(d, sort_keys=True, separators=(",", ":"))
    log.path.write_text("\n".join(lines) + "\n")
    with pytest.raises(AuditChainBrokenError):
        log.verify()


def test_denial_log_observer_end_to_end(tmp_path):
    log = DenialLog(dir_path=tmp_path)
    pipe = AdapterPipeline([_Deny()], observer=log.observer())
    pipe.run_pre(ctx("read_file", {"path": "/etc/shadow"}))
    recs = log.records()
    assert len(recs) == 1
    assert recs[0]["ref"] == "read_file"
    assert "blocked for testing" in recs[0]["detail"]


def test_denial_log_warns_off_by_default(tmp_path):
    log = DenialLog(dir_path=tmp_path)  # log_warns defaults False
    pipe = AdapterPipeline([_Warn()], observer=log.observer())
    pipe.run_pre(ctx("x"))
    assert log.records() == []


def test_denial_log_warns_when_enabled(tmp_path):
    log = DenialLog(dir_path=tmp_path, log_warns=True)
    pipe = AdapterPipeline([_Warn()], observer=log.observer())
    pipe.run_pre(ctx("x"))
    recs = log.records()
    assert len(recs) == 1 and recs[0]["event"] == "warn"


def test_denial_log_value_free(tmp_path):
    # A well-behaved adapter's reason never contains a secret value; confirm
    # the log stores only the reason string, nothing else from the ctx.
    log = DenialLog(dir_path=tmp_path)

    class _SecretReason(Adapter):
        name = "leaky"
        def pre_action(self, c):
            return Verdict.deny(self.name, "credential material in tool arguments")

    pipe = AdapterPipeline([_SecretReason()], observer=log.observer())
    pipe.run_pre(ctx("http-post", {"body": "key=sk_live_SHOULD_NOT_APPEAR"}))
    raw = log.path.read_text()
    assert "sk_live_SHOULD_NOT_APPEAR" not in raw
