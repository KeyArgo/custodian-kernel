import subprocess

from custodian.cli.main import main


def test_uninstall_dry_run_preserves_data(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("custodian.cli.cmd_uninstall.Path.home", lambda: tmp_path)
    calls = []
    monkeypatch.setattr(
        "custodian.cli.cmd_uninstall.subprocess.run",
        lambda command: calls.append(command),
    )
    assert main(["uninstall", "--dry-run"]) == 0
    assert calls == []
    output = capsys.readouterr().out
    assert ".custodian" in output
    assert ".paladin" in output
    assert "not deleted" in output


def test_uninstall_requires_explicit_yes(monkeypatch):
    monkeypatch.setattr(
        "custodian.cli.cmd_uninstall.subprocess.run",
        lambda command: (_ for _ in ()).throw(AssertionError("pip must not run")),
    )
    assert main(["uninstall"]) == 2


def test_uninstall_invokes_pip_without_deleting_data(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "custodian.cli.cmd_uninstall.subprocess.run",
        lambda command: calls.append(command) or subprocess.CompletedProcess(command, 0),
    )
    assert main(["uninstall", "--yes"]) == 0
    assert calls and calls[0][-3:] == ["uninstall", "-y", "custodian-kernel"]
