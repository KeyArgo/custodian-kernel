"""The interactive menu must build the right argv for the real CLI, so a user
never has to type long syntax. It re-implements no command logic — it asks
questions and delegates to paladin.cli.main — so these tests assert the argv it
assembles, and that a bare `paladin` in a non-interactive context prints help
rather than hanging on a menu prompt.
"""
import builtins

import pytest

from paladin import menu as m


@pytest.fixture
def captured(monkeypatch):
    """Capture the argv the menu hands to the CLI, without running it."""
    calls = []
    monkeypatch.setattr(m, "_run", lambda argv: calls.append(argv))
    return calls


def _feed(monkeypatch, answers):
    it = iter(answers)
    monkeypatch.setattr(builtins, "input", lambda *a, **k: next(it))


def test_list_builds_list_argv(captured, monkeypatch):
    m._act_list()
    assert captured == [["list"]]


def test_add_builds_add_argv_with_kind_and_env(captured, monkeypatch):
    _feed(monkeypatch, ["stripe_key", "secret", "STRIPE_KEY"])
    m._act_add()
    assert captured == [["add", "stripe_key", "--kind", "secret",
                         "--env-var", "STRIPE_KEY"]]


def test_run_with_secret_builds_exec_argv(captured, monkeypatch):
    _feed(monkeypatch, ["stripe_key", "MY_KEY", "python bill.py"])
    m._act_run_with_secret()
    assert captured == [["exec", "--with", "stripe_key=MY_KEY", "--",
                         "python", "bill.py"]]


def test_run_with_secret_strips_quotes_in_command(captured, monkeypatch):
    """python -c "code" must reach the child with the quotes stripped."""
    _feed(monkeypatch, ["k", "K", 'python -c "print(1)"'])
    m._act_run_with_secret()
    assert captured == [["exec", "--with", "k=K", "--",
                         "python", "-c", "print(1)"]]


def test_import_csv_dry_run_argv(captured, monkeypatch):
    # choose csv (option 3 in the import submenu), give a path, say yes to preview
    _feed(monkeypatch, ["3", "export.csv", "y"])
    m._act_import()
    assert captured == [["import", "csv", "export.csv", "--dry-run"]]


def test_delete_requires_matching_confirmation(captured, monkeypatch):
    _feed(monkeypatch, ["stripe_key", "wrong_name"])
    m._act_delete()
    assert captured == []  # mismatch -> nothing deleted


def test_delete_confirmed(captured, monkeypatch):
    _feed(monkeypatch, ["stripe_key", "stripe_key"])
    m._act_delete()
    assert captured == [["rm", "stripe_key"]]


def test_bare_paladin_non_tty_prints_help_not_menu(monkeypatch, capsys):
    """A pipe/script/CI must get help, never a menu that hangs on stdin."""
    from paladin import cli
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    rc = cli.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "usage: paladin" in out
    assert "menu" in out  # the menu subcommand is advertised


def test_menu_subcommand_is_registered():
    from paladin import cli
    parser = cli.build_parser()
    # argparse should accept "menu" as a valid subcommand
    args = parser.parse_args(["menu"])
    assert args.fn is cli.cmd_menu
