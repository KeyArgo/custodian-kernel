"""Masked secret entry — shows a ``*`` per character so the human can see their
keystrokes register, instead of getpass's completely blank line.

The value is never displayed (only ``*``), never logged, and never leaves this
function except as the returned string — the same contract getpass gives, with
visible feedback. Backspace works. On a non-interactive stdin (a pipe, ``--stdin``,
a test) it reads a line normally, and if no per-key backend is available it
falls back to getpass, so it degrades safely everywhere.
"""
from __future__ import annotations

import sys


def _read_line_plain() -> str:
    return sys.stdin.readline().rstrip("\n").rstrip("\r")


def _read_masked_windows(prompt: str) -> str:
    import msvcrt

    sys.stdout.write(prompt)
    sys.stdout.flush()
    buf: list[str] = []
    while True:
        ch = msvcrt.getwch()
        if ch in ("\r", "\n"):
            sys.stdout.write("\n")
            sys.stdout.flush()
            return "".join(buf)
        if ch == "\x03":  # Ctrl-C
            raise KeyboardInterrupt
        if ch in ("\b", "\x7f"):  # backspace
            if buf:
                buf.pop()
                sys.stdout.write("\b \b")
                sys.stdout.flush()
            continue
        if ch == "\x00" or ch == "\xe0":  # a function/arrow key: consume the 2nd byte, ignore
            msvcrt.getwch()
            continue
        buf.append(ch)
        sys.stdout.write("*")
        sys.stdout.flush()


def _read_masked_posix(prompt: str) -> str:
    import termios
    import tty

    sys.stdout.write(prompt)
    sys.stdout.flush()
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    buf: list[str] = []
    try:
        tty.setraw(fd)
        while True:
            ch = sys.stdin.read(1)
            if ch in ("\r", "\n"):
                return "".join(buf)
            if ch == "\x03":  # Ctrl-C
                raise KeyboardInterrupt
            if ch in ("\x7f", "\b"):  # backspace/delete
                if buf:
                    buf.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
                continue
            if ch == "\x15":  # Ctrl-U: clear line
                while buf:
                    buf.pop()
                    sys.stdout.write("\b \b")
                sys.stdout.flush()
                continue
            buf.append(ch)
            sys.stdout.write("*")
            sys.stdout.flush()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write("\n")
        sys.stdout.flush()


def read_secret(prompt: str) -> str:
    """Prompt for a secret, echoing ``*`` per character. See module docstring."""
    # Not a real terminal (pipe / --stdin / test): read a line, no masking.
    try:
        interactive = sys.stdin.isatty()
    except Exception:
        interactive = False
    if not interactive:
        return _read_line_plain()

    try:
        if sys.platform == "win32":
            return _read_masked_windows(prompt)
        return _read_masked_posix(prompt)
    except (ImportError, OSError):
        # No per-key backend available (unusual terminal); fall back to
        # getpass — no visible feedback, but still correct and never echoed.
        import getpass
        return getpass.getpass(prompt)
