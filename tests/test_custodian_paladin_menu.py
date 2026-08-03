"""Custodian's menu links to, but never absorbs, the Paladin console."""

from custodian.cli import menu


def test_custodian_menu_opens_separate_paladin_console(monkeypatch):
    called = []
    monkeypatch.setattr(
        menu.subprocess, "run",
        lambda argv, **kwargs: called.append((argv, kwargs)),
    )
    menu._act_paladin()
    assert called == [([menu.sys.executable, "-m", "paladin.cli"], {"check": False})]
