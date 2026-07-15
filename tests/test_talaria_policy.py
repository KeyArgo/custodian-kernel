"""Talaria policy compiler + hermes install/status tests."""
import pytest

from custodian.adapters.base import ActionContext
from talaria.policy import build_pipeline, load_policy, STARTER_POLICY
from talaria.cli import main as talaria_main


def ctx(skill, args=None, **kw):
    return ActionContext(skill=skill, args=args or {}, **kw)


# -- policy compiler ----------------------------------------------------------

def test_build_pipeline_forbidden_path():
    pol = {"paths": {"forbid": ["~/.ssh"]}, "guards": {}}
    pipe = build_pipeline(pol)
    r = pipe.run_pre(ctx("read_file", {"path": "~/.ssh/id_rsa"}))
    assert not r.allowed


def test_build_pipeline_forbidden_tool():
    pol = {"tools": {"forbid": ["stripe-payout"]}, "guards": {}}
    pipe = build_pipeline(pol)
    assert not pipe.run_pre(ctx("stripe-payout")).allowed
    assert pipe.run_pre(ctx("read_file", {"path": "/tmp/ok.txt"})).allowed


def test_build_pipeline_always_on_secret_leak():
    # secret_leak is on by default even with an otherwise-empty policy
    pipe = build_pipeline({})
    assert not pipe.run_pre(
        ctx("http-post", {"body": "key=sk_live_abcdefghijklmnop"})).allowed


def test_build_pipeline_can_disable_optional_guard():
    # repetition is optional; turning it off must drop it.
    pol = {"guards": {"repetition": False, "pii": False}}
    pipe = build_pipeline(pol)
    names = [a.name for a in pipe.adapters]
    assert "repetition-breaker" not in names
    assert "pii-redactor" not in names


def test_build_pipeline_kernel_grade_guards_cannot_be_disabled():
    # self_protection/prompt_injection/secret_leak are documented as
    # "cannot be disabled by policy" — setting them false in policy.yaml
    # must NOT drop them. Regression test for a bug found in adversarial
    # review where guards.get(..., True) let a policy file disable them.
    pol = {"guards": {"self_protection": False, "prompt_injection": False,
                      "secret_leak": False}}
    pipe = build_pipeline(pol)
    names = [a.name for a in pipe.adapters]
    assert "kernel-self-protection" in names
    assert "prompt-injection-guard" in names
    assert "secret-leak-guard" in names


def test_build_pipeline_malformed_guards_does_not_crash():
    # A scalar where a mapping was expected (an easy YAML typo:
    # "guards: true" instead of "guards: {...}") must not blow up
    # build_pipeline before any guard is added.
    pol = {"guards": True, "tools": True, "paths": True}
    pipe = build_pipeline(pol)
    names = [a.name for a in pipe.adapters]
    assert "kernel-self-protection" in names  # kernel-grade guards still added


def test_build_pipeline_empty_redact_still_enables_pii_guard():
    # pii: true (the default) with an empty/absent redact list must still
    # add the guard — it should redact every kind by default, not silently
    # no-op. This is what the shipped STARTER_POLICY sets out of the box.
    pol = {"privacy": {"redact": []}}
    pipe = build_pipeline(pol)
    names = [a.name for a in pipe.adapters]
    assert "pii-redactor" in names
    r = pipe.run_pre(ctx("write_file", {"content": "reach me at a@b.com"}))
    assert r.transforms


def test_build_pipeline_wires_denial_observer():
    seen = []
    pol = {"paths": {"forbid": ["/etc"]}, "log_denials": True}
    pipe = build_pipeline(pol, denial_observer=lambda c, v: seen.append(v.adapter))
    pipe.run_pre(ctx("write_file", {"file_path": "/etc/passwd"}))
    assert "path-fence" in seen


def test_starter_policy_is_valid_yaml():
    import yaml
    doc = yaml.safe_load(STARTER_POLICY)
    assert "paths" in doc and "guards" in doc


def test_load_policy_missing_returns_empty(tmp_path):
    assert load_policy(tmp_path / "nope.yaml") == {}


# -- hermes install / status --------------------------------------------------

def test_hermes_install_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("TALARIA_HOME", str(tmp_path / "talaria"))
    monkeypatch.setenv("WARDEN_HOME", str(tmp_path / "warden"))
    rc = talaria_main(["hermes", "install"])
    assert rc == 0
    assert (tmp_path / "hermes" / "plugins" / "talaria-guard" / "plugin.yaml").exists()
    assert (tmp_path / "hermes" / "plugins" / "talaria-guard" / "__init__.py").exists()
    assert (tmp_path / "talaria" / "policy.yaml").exists()


def test_hermes_install_idempotent_preserves_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("TALARIA_HOME", str(tmp_path / "talaria"))
    monkeypatch.setenv("WARDEN_HOME", str(tmp_path / "warden"))
    talaria_main(["hermes", "install"])
    pol = tmp_path / "talaria" / "policy.yaml"
    pol.write_text("tools:\n  forbid: [my-custom-rule]\n")  # user edits
    talaria_main(["hermes", "install"])  # re-run
    assert "my-custom-rule" in pol.read_text()  # not clobbered


def test_hermes_status_reports_installed(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("TALARIA_HOME", str(tmp_path / "talaria"))
    monkeypatch.setenv("WARDEN_HOME", str(tmp_path / "warden"))
    talaria_main(["hermes", "install"])
    capsys.readouterr()
    talaria_main(["hermes", "status"])
    out = capsys.readouterr().out
    assert "plugin installed: yes" in out
    assert "denial logging:   on" in out
