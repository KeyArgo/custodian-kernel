from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

INSTALLER = Path(__file__).resolve().parents[1] / "scripts/install-custodian.py"


def _module():
    spec = importlib.util.spec_from_file_location("custodian_installer", INSTALLER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_installer_uses_managed_venv_not_system_pip():
    source = INSTALLER.read_text(encoding="utf-8")
    assert "venv.EnvBuilder" in source
    assert "_runtime_python(candidate)" in source
    assert "--break-system-packages" not in source
    assert "--user" not in source


def test_installer_never_names_data_directories_for_deletion():
    source = INSTALLER.read_text(encoding="utf-8")
    for protected in (".custodian", ".paladin", ".talaria"):
        assert protected not in source


def test_dry_run_is_side_effect_free(tmp_path):
    runtime = tmp_path / "runtime-root"
    commands = tmp_path / "bin"
    result = subprocess.run(
        [
            os.fspath(Path(os.sys.executable)), os.fspath(INSTALLER),
            "--package", "local.whl", "--runtime-root", os.fspath(runtime),
            "--bin-dir", os.fspath(commands), "--dry-run",
        ],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert not runtime.exists()
    assert not commands.exists()
    assert "user data: preserved" in result.stdout


def test_existing_launcher_is_backed_up(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setattr(module.os, "name", "posix")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    destination = bin_dir / "custodian"
    destination.write_text("old launcher")
    target = tmp_path / "runtime/bin/custodian"
    target.parent.mkdir(parents=True)
    target.write_text("new launcher")
    module._expose("custodian", target, bin_dir)
    assert destination.is_symlink()
    assert (bin_dir / "custodian.previous").read_text() == "old launcher"


def test_upgrade_preserves_original_launcher_backup(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setattr(module.os, "name", "posix")
    root = tmp_path / "managed"
    first = root / "runtime-a/bin/custodian"
    second = root / "runtime-b/bin/custodian"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text("first")
    second.write_text("second")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    launcher = bin_dir / "custodian"
    launcher.write_text("original")

    module._expose("custodian", first, bin_dir, runtime_root=root)
    module._expose("custodian", second, bin_dir, runtime_root=root)

    assert launcher.resolve() == second
    assert (bin_dir / "custodian.previous").read_text() == "original"


def test_failed_staging_install_cannot_replace_current_runtime(tmp_path, monkeypatch):
    module = _module()
    root = tmp_path / "managed"
    current = root / "runtime"
    current.mkdir(parents=True)
    marker = current / "KEEP"
    marker.write_text("working")
    monkeypatch.setattr(module.venv.EnvBuilder, "create", lambda self, path: Path(path).mkdir(parents=True))
    monkeypatch.setattr(
        module.subprocess, "run",
        lambda *a, **kw: (_ for _ in ()).throw(subprocess.CalledProcessError(1, a[0])),
    )
    try:
        module.install("broken.whl", root, tmp_path / "bin")
    except subprocess.CalledProcessError:
        pass
    assert marker.read_text() == "working"


def test_install_uses_fixed_slots_because_venvs_cannot_be_renamed():
    source = INSTALLER.read_text(encoding="utf-8")
    assert '"runtime-a"' in source
    assert '"runtime-b"' in source
    assert "candidate.replace" not in source
    assert "staging.replace" not in source


def test_managed_uninstall_removes_only_owned_runtime_and_restores_launcher(
    tmp_path, monkeypatch
):
    module = _module()
    monkeypatch.setattr(module.os, "name", "posix")
    root = tmp_path / "managed"
    runtime = root / "runtime"
    target = runtime / "bin/custodian"
    target.parent.mkdir(parents=True)
    target.write_text("installed")
    commands = tmp_path / "bin"
    commands.mkdir()
    launcher = commands / "custodian"
    launcher.symlink_to(target)
    backup = commands / "custodian.previous"
    backup.write_text("old launcher")
    unrelated = commands / "unrelated"
    unrelated.write_text("keep")

    module.uninstall(root, commands)

    assert not root.exists()
    assert root.with_name("managed.removed").exists()
    assert launcher.read_text() == "old launcher"
    assert unrelated.read_text() == "keep"


def test_managed_uninstall_does_not_remove_unowned_launcher(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setattr(module.os, "name", "posix")
    root = tmp_path / "managed"
    (root / "runtime").mkdir(parents=True)
    commands = tmp_path / "bin"
    commands.mkdir()
    external = tmp_path / "someone-elses-custodian"
    external.write_text("keep")
    (commands / "custodian").symlink_to(external)

    module.uninstall(root, commands)

    assert (commands / "custodian").resolve() == external


def test_managed_paths_reject_home_root_and_nested_command_dir(tmp_path):
    module = _module()
    for runtime, commands in (
        (Path("/"), tmp_path / "bin"),
        (Path.home(), tmp_path / "bin"),
        (tmp_path / "managed", tmp_path / "managed/bin"),
    ):
        try:
            module._validate_managed_paths(runtime, commands)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe paths accepted: {runtime}, {commands}")


def test_managed_paths_reject_symlinked_runtime_root(tmp_path):
    module = _module()
    target = tmp_path / "target"
    target.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)
    try:
        module._validate_managed_paths(alias, tmp_path / "bin")
    except ValueError:
        pass
    else:
        raise AssertionError("symlinked runtime root was accepted")
