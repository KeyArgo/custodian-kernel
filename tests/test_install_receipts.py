"""Tests for the install-receipt and version-drift detection in
``custodian setup`` / ``custodian doctor``.

The receipt is plain JSON written to ``$CUSTODIAN_STATE_DIR/install-receipt.json``
after a successful ``setup`` run, recording the kernel version, the
components installed, and the interpreter path.  ``doctor`` reads it and
emits a clear warning when the recorded kernel version no longer matches
the running one — a hard-to-miss reminder that ``setup`` needs to be
re-run after a ``pip install -U custodian-kernel``.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from custodian.cli.main import main
from custodian.cli import cmd_setup


_SHIPPED_YAML = (
    Path(__file__).resolve().parent.parent
    / "custodian" / "guards" / "hermes" / "plugin" / "plugin.yaml"
).read_text()


@pytest.fixture(autouse=True)
def no_real_hermes(monkeypatch, tmp_path):
    """Doctor must not pick up the real host's Hermes install or any
    existing install receipt."""
    monkeypatch.setattr("custodian.cli.cmd_doctor.shutil.which", lambda name: None)
    monkeypatch.setattr("custodian.cli.cmd_doctor.Path.home", lambda: tmp_path)
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.setenv("CUSTODIAN_STATE_DIR", str(tmp_path / "state"))


def _seed_hermes_env(monkeypatch, tmp_path):
    """Create a minimal Hermes environment so ``doctor --profile hermes``
    reaches the receipt check at the end of the run."""
    real_find_spec = __import__("importlib").util.find_spec
    monkeypatch.setattr(
        "custodian.cli.cmd_doctor.importlib.util.find_spec",
        lambda name: object() if name == "talaria" else real_find_spec(name),
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("TALARIA_HOME", str(tmp_path / "talaria"))
    hermes = tmp_path / "hermes"
    (hermes / "plugins" / "talaria-guard").mkdir(parents=True)
    (hermes / "plugins" / "talaria-guard" / "plugin.yaml").write_text("name: guard\n")
    (hermes / "plugins" / "custodian-hermes-guard").mkdir(parents=True)
    (hermes / "plugins" / "custodian-hermes-guard" / "plugin.yaml").write_text(_SHIPPED_YAML)
    talaria = tmp_path / "talaria"
    talaria.mkdir()
    (talaria / "policy.yaml").write_text("{}\n")
    return tmp_path / "state"


# --- receipt writing --------------------------------------------------------


def test_write_install_receipt_creates_file(tmp_path):
    target = cmd_setup._write_install_receipt(tmp_path, ["hermes-guard", "paladin"])
    assert target.exists()
    data = json.loads(target.read_text())
    assert data["schema"] == "custodian.install-receipt.v1"
    assert data["components"] == ["hermes-guard", "paladin"]
    assert data["interpreter"] == sys.executable
    assert "kernel_version" in data
    assert "installed_at" in data
    # installed_at is a unix timestamp; ~now.
    now = __import__("time").time()
    assert abs(data["installed_at"] - now) < 5


def test_write_install_receipt_is_atomic(tmp_path):
    """The .tmp + replace pattern means we never observe a partial file
    even on crash mid-write."""
    target = cmd_setup._write_install_receipt(tmp_path, ["paladin"])
    assert not target.with_suffix(".json.tmp").exists()
    assert target.exists()


def test_receipt_path_resolves_state_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("CUSTODIAN_STATE_DIR", str(tmp_path / "explicit"))
    sd = cmd_setup._state_dir()
    assert sd == tmp_path / "explicit"
    assert cmd_setup._receipt_path(sd) == tmp_path / "explicit" / "install-receipt.json"


def test_receipt_path_defaults_to_home(monkeypatch, tmp_path):
    monkeypatch.delenv("CUSTODIAN_STATE_DIR", raising=False)
    monkeypatch.setattr("custodian.cli.cmd_setup.Path.home", lambda: tmp_path)
    sd = cmd_setup._state_dir()
    assert sd == tmp_path / ".custodian"


# --- doctor version-drift detection ---------------------------------------


def test_doctor_warns_on_version_drift(monkeypatch, tmp_path, capsys):
    """A receipt whose kernel_version differs from the running version
    must produce a visible warning, but must NOT change the exit code
    (a stale receipt is a soft signal — setup is the fix, not a hard
    failure)."""
    state = _seed_hermes_env(monkeypatch, tmp_path)
    state.mkdir(parents=True, exist_ok=True)
    receipt = state / "install-receipt.json"
    receipt.write_text(json.dumps({
        "schema": "custodian.install-receipt.v1",
        "kernel_version": "0.0.1-old",  # deliberately different
        "components": ["hermes-guard"],
        "interpreter": sys.executable,
        "installed_at": 0.0,
    }))
    # Force _kernel_version() to return something other than 0.0.1-old.
    monkeypatch.setattr(
        "custodian.cli.cmd_setup._kernel_version", lambda: "9.9.9-new",
    )

    rc = main(["doctor", "--profile", "hermes"])
    out = capsys.readouterr().out
    assert "version drift" in out.lower()
    assert "0.0.1-old" in out
    assert "9.9.9-new" in out
    assert "custodian setup" in out
    # Soft signal: doctor still reports Ready (only hard failures raise rc).
    assert rc == 0


def test_doctor_silent_when_versions_match(monkeypatch, tmp_path, capsys):
    state = _seed_hermes_env(monkeypatch, tmp_path)
    state.mkdir(parents=True, exist_ok=True)
    state / "install-receipt.json"
    monkeypatch.setattr(
        "custodian.cli.cmd_setup._kernel_version", lambda: "1.2.3"
    )
    (state / "install-receipt.json").write_text(json.dumps({
        "schema": "custodian.install-receipt.v1",
        "kernel_version": "1.2.3",
        "components": ["hermes-guard"],
        "interpreter": sys.executable,
        "installed_at": 0.0,
    }))

    rc = main(["doctor", "--profile", "hermes"])
    out = capsys.readouterr().out
    assert "version drift" not in out.lower()
    assert "Ready" in out
    assert rc == 0


def test_doctor_no_receipt_is_silent(monkeypatch, tmp_path, capsys):
    """No receipt present at all (fresh install) — silent, no warning."""
    _seed_hermes_env(monkeypatch, tmp_path)  # receipt dir not created

    rc = main(["doctor", "--profile", "hermes"])
    out = capsys.readouterr().out
    assert "version drift" not in out.lower()
    assert "Ready" in out
    assert rc == 0


def test_doctor_malformed_receipt_is_swallowed(monkeypatch, tmp_path, capsys):
    """A corrupted receipt (e.g. partial write) must never break doctor;
    the receipt is best-effort metadata, not a hard dependency."""
    state = _seed_hermes_env(monkeypatch, tmp_path)
    state.mkdir(parents=True, exist_ok=True)
    (state / "install-receipt.json").write_text("{not valid json")

    rc = main(["doctor", "--profile", "hermes"])
    out = capsys.readouterr().out
    assert "version drift" not in out.lower()
    assert rc == 0  # don't block on a broken receipt
