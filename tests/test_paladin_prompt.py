"""Masked secret entry: shows a `*` per character (so the user sees keystrokes
register), never the characters themselves; reads a line on a non-interactive
stdin; and returns exactly what was typed.
"""
import io
import sys
import types
from unittest import mock

import pytest

from paladin import _prompt


def _drive_windows(keys, monkeypatch):
    """Run read_secret through the Windows masked path with `keys` fed to
    msvcrt.getwch, capturing what lands on screen."""
    seq = iter(keys)
    fake = types.ModuleType("msvcrt")
    fake.getwch = lambda: next(seq)
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    monkeypatch.setattr(_prompt.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(_prompt.sys, "platform", "win32")
    out = io.StringIO()
    monkeypatch.setattr(_prompt.sys, "stdout", out)
    value = _prompt.read_secret("value: ")
    return value, out.getvalue()


def test_masks_characters_with_stars(monkeypatch):
    value, screen = _drive_windows(list("sk_live_x") + ["\r"], monkeypatch)
    assert value == "sk_live_x"
    assert "sk_live_x" not in screen        # the actual value is never shown
    assert screen.count("*") == len("sk_live_x")


def test_backspace_removes_a_char(monkeypatch):
    # type "abX", backspace, "c" -> "abc"
    value, screen = _drive_windows(["a", "b", "X", "\b", "c", "\r"], monkeypatch)
    assert value == "abc"


def test_ctrl_c_raises_keyboardinterrupt(monkeypatch):
    with pytest.raises(KeyboardInterrupt):
        _drive_windows(["a", "\x03"], monkeypatch)


def test_arrow_key_prefix_is_ignored(monkeypatch):
    # \xe0 then 'H' (up arrow) should be swallowed, not added to the value
    value, _ = _drive_windows(["a", "\xe0", "H", "b", "\r"], monkeypatch)
    assert value == "ab"


def test_non_interactive_reads_a_line(monkeypatch):
    monkeypatch.setattr(_prompt.sys, "stdin", io.StringIO("piped-secret\n"))
    # isatty on a StringIO is False -> line-read path
    assert _prompt.read_secret("value: ") == "piped-secret"


def test_falls_back_to_getpass_when_no_backend(monkeypatch):
    monkeypatch.setattr(_prompt.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(_prompt.sys, "platform", "linux")
    # posix path imports termios; force it to fail -> getpass fallback
    monkeypatch.setattr(_prompt, "_read_masked_posix",
                        lambda p: (_ for _ in ()).throw(ImportError))
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "from-getpass")
    assert _prompt.read_secret("value: ") == "from-getpass"
