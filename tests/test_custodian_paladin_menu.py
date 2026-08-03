"""Custodian's menu links to, but never absorbs, the Paladin console."""

from custodian.cli import menu


def test_custodian_menu_opens_separate_paladin_console(monkeypatch):
    called = []
    monkeypatch.setattr("paladin.menu.run_menu", lambda: called.append(True))
    menu._act_paladin()
    assert called == [True]
