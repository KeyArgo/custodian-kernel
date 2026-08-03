"""The custodian interactive menu builds the right argv and delegates to the
real CLI (custodian.cli.main.main), so no command logic is duplicated. Same
approach as the paladin menu tests.
"""
import builtins

import pytest

from custodian.cli import menu as m


@pytest.fixture
def captured(monkeypatch):
    calls = []
    monkeypatch.setattr(m, "_run", lambda argv: calls.append(argv))
    return calls


def _feed(monkeypatch, answers):
    it = iter(answers)
    monkeypatch.setattr(builtins, "input", lambda *a, **k: next(it))


def test_status_argv(captured):
    m._act_status()
    assert captured == [["status"]]


def test_request_argv(captured, monkeypatch):
    _feed(monkeypatch, ["5.00", "API credits"])
    m._act_request()
    assert captured == [["request", "--amount", "5.00", "--description", "API credits"]]


def test_kill_argv_with_reason(captured, monkeypatch):
    _feed(monkeypatch, ["alice", "maintenance"])
    m._act_kill()
    assert captured == [["kill", "--by", "alice", "--reason", "maintenance"]]


def test_resume_argv(captured, monkeypatch):
    _feed(monkeypatch, ["alice"])
    m._act_resume()
    assert captured == [["resume", "--by", "alice"]]


def test_menu_subcommand_dispatches_to_menu(monkeypatch):
    """`custodian menu` must route to the interactive menu."""
    from custodian.cli import main as cli_main
    called = []
    monkeypatch.setattr(cli_main, "_run_menu", lambda: (called.append(True), 0)[1])
    rc = cli_main.main(["menu"])
    assert rc == 0 and called == [True]


@pytest.mark.parametrize("answer", ["q", "quit", "exit", "0"])
def test_menu_quit_aliases_exit_cleanly(monkeypatch, capsys, answer):
    _feed(monkeypatch, [answer])
    assert m.run_menu() == 0
    assert "bye." in capsys.readouterr().out


def test_menu_is_authority_first_and_spend_is_secondary():
    labels = dict(m._ACTIONS)
    assert labels["status"] == "Show safety and authority status"
    assert m._ACTIONS.index(("request", labels["request"])) > m._ACTIONS.index(
        ("guide", labels["guide"])
    )


def test_bare_custodian_non_tty_prints_welcome(monkeypatch, capsys):
    from custodian.cli import main as cli_main
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    rc = cli_main.main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.strip()  # welcome text, not a crash
