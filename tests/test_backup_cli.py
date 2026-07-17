"""`custodian backup` / `custodian restore` — workspace data safety.

Run in-process (not via subprocess) so they are fast and locale-proof;
the commands are pure argparse + file work with no interactive input.
"""
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from custodian.cli.main import main


def _make_workspace(root: Path) -> None:
    """A minimal real workspace: policy.yaml + state/custodian.db + mirror."""
    (root / "policy.yaml").write_text("bands:\n  L2:\n    cap: 25.0\n")
    state = root / "state"
    state.mkdir()
    db = sqlite3.connect(str(state / "custodian.db"))
    db.execute("CREATE TABLE spend (id INTEGER PRIMARY KEY, amount REAL)")
    db.execute("INSERT INTO spend (amount) VALUES (12.5)")
    db.commit()
    db.close()
    (state / "kill_switch.json").write_text('{"killed": false}')


def _run(root: Path, *argv: str) -> int:
    return main([*argv, "--state-dir", str(root / "state"),
                 "--policy", str(root / "policy.yaml")])


def test_backup_creates_archive_with_manifest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_workspace(tmp_path)
    dest = tmp_path / "b.zip"
    assert _run(tmp_path, "backup", str(dest)) == 0
    with zipfile.ZipFile(dest) as zf:
        names = set(zf.namelist())
        assert "MANIFEST.json" in names
        assert "policy.yaml" in names
        assert "state/custodian.db" in names
        assert "state/kill_switch.json" in names
        manifest = json.loads(zf.read("MANIFEST.json"))
        assert manifest["format"] == "custodian-backup/1"


def test_backup_db_snapshot_is_a_valid_database(tmp_path, monkeypatch):
    """The archived db must be a consistent SQLite snapshot, not a raw
    (potentially torn) file copy — prove it opens and holds the data."""
    monkeypatch.chdir(tmp_path)
    _make_workspace(tmp_path)
    dest = tmp_path / "b.zip"
    assert _run(tmp_path, "backup", str(dest)) == 0
    out = tmp_path / "extracted.db"
    with zipfile.ZipFile(dest) as zf:
        out.write_bytes(zf.read("state/custodian.db"))
    db = sqlite3.connect(str(out))
    assert db.execute("SELECT amount FROM spend").fetchone()[0] == 12.5
    db.close()


def test_backup_with_no_workspace_fails_helpfully(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert _run(tmp_path, "backup", str(tmp_path / "b.zip")) == 1
    assert "custodian init" in capsys.readouterr().out


def test_backup_to_directory_picks_timestamped_name(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_workspace(tmp_path)
    outdir = tmp_path / "backups"
    outdir.mkdir()
    assert _run(tmp_path, "backup", str(outdir)) == 0
    assert len(list(outdir.glob("custodian-backup-*.zip"))) == 1


def test_restore_to_empty_machine(tmp_path, monkeypatch):
    """The migration story: back up machine 1, restore into an empty
    directory (machine 2), byte-identical data comes back."""
    m1 = tmp_path / "m1"
    m1.mkdir()
    monkeypatch.chdir(m1)
    _make_workspace(m1)
    backup = tmp_path / "b.zip"
    assert _run(m1, "backup", str(backup)) == 0

    m2 = tmp_path / "m2"
    m2.mkdir()
    monkeypatch.chdir(m2)
    assert _run(m2, "restore", str(backup)) == 0
    assert (m2 / "policy.yaml").read_text() == (m1 / "policy.yaml").read_text()
    db = sqlite3.connect(str(m2 / "state" / "custodian.db"))
    assert db.execute("SELECT amount FROM spend").fetchone()[0] == 12.5
    db.close()


def test_restore_refuses_existing_workspace_without_force(tmp_path, monkeypatch, capsys):
    m1 = tmp_path / "m1"
    m1.mkdir()
    monkeypatch.chdir(m1)
    _make_workspace(m1)
    backup = tmp_path / "b.zip"
    assert _run(m1, "backup", str(backup)) == 0
    # restoring over the SAME live workspace must refuse
    assert _run(m1, "restore", str(backup)) == 1
    assert "--force" in capsys.readouterr().out


def test_restore_force_saves_pre_restore_zip(tmp_path, monkeypatch):
    m1 = tmp_path / "m1"
    m1.mkdir()
    monkeypatch.chdir(m1)
    _make_workspace(m1)
    backup = tmp_path / "b.zip"
    assert _run(m1, "backup", str(backup)) == 0

    # change the live policy, then force-restore the older backup
    (m1 / "policy.yaml").write_text("bands:\n  L2:\n    cap: 99.0\n")
    assert _run(m1, "restore", str(backup), "--force") == 0
    assert "cap: 25.0" in (m1 / "policy.yaml").read_text()  # backup won
    safety = list(m1.glob("pre-restore-*.zip"))
    assert len(safety) == 1
    with zipfile.ZipFile(safety[0]) as zf:  # the newer policy is preserved
        assert b"cap: 99.0" in zf.read("policy.yaml")


def test_restore_rejects_non_backup_zip(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    junk = tmp_path / "junk.zip"
    with zipfile.ZipFile(junk, "w") as zf:
        zf.writestr("random.txt", "hi")
    assert _run(tmp_path, "restore", str(junk)) == 1
    assert "not a custodian backup" in capsys.readouterr().out


def test_restore_rejects_zip_slip_paths(tmp_path, monkeypatch, capsys):
    """An archive member must never escape the workspace."""
    monkeypatch.chdir(tmp_path)
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("MANIFEST.json", json.dumps({"format": "custodian-backup/1"}))
        zf.writestr("state/../../outside.txt", "escaped")
    assert _run(tmp_path, "restore", str(evil)) == 1
    assert "unsafe path" in capsys.readouterr().out
    assert not (tmp_path.parent / "outside.txt").exists()


def test_restore_rejects_unexpected_members(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    odd = tmp_path / "odd.zip"
    with zipfile.ZipFile(odd, "w") as zf:
        zf.writestr("MANIFEST.json", json.dumps({"format": "custodian-backup/1"}))
        zf.writestr("somewhere-else.txt", "nope")
    assert _run(tmp_path, "restore", str(odd)) == 1
    assert "unexpected member" in capsys.readouterr().out
