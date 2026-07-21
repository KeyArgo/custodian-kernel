"""Console-encoding safety for the CLIs.

Custodian's CLIs print status glyphs (checkmarks, arrows, box-drawing,
``≤``) and ANSI colour. On Windows the default console code page is
cp1252, whose ``charmap`` codec cannot encode any of those characters, so the
very first ``print`` raises ``UnicodeEncodeError`` and every command — including
``--help`` and the flagship ``custodian-verify`` — dies with a confusing
``error: 'charmap' codec can't encode...`` line.

Reconfiguring stdout/stderr to UTF-8 at process entry fixes this everywhere the
stream supports it (a real terminal or a pipe). Where it does not (e.g. a
pytest capture object that has no ``reconfigure``), we fall back to an
error-tolerant write so output degrades to ``?`` placeholders instead of
crashing. Called once from each CLI ``main()``.
"""
from __future__ import annotations

import os
import re
import sys

# SGR (color/style) escape sequences only -- cursor movement etc. is never
# emitted by these CLIs, so a conservative pattern avoids eating real output.
_SGR = re.compile(r"\x1b\[[0-9;]*m")


class _AnsiStrippingWriter:
    """Proxy that removes ANSI SGR codes from everything written.

    The CLIs hardcode color escapes; when output is piped (or NO_COLOR is set)
    those arrive as literal ``[1;32m`` garbage. Stripping centrally here keeps
    the eight emitting modules untouched and honours the NO_COLOR convention.
    """

    def __init__(self, stream):
        self._stream = stream

    def write(self, s):
        return self._stream.write(_SGR.sub("", s))

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def __getattr__(self, name):
        return getattr(self._stream, name)


def _wants_color(stream) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def force_utf8_io() -> None:
    """Make stdout/stderr encode UTF-8, or at least never crash on a glyph.

    Also strips ANSI color codes when the stream is not an interactive
    terminal or the NO_COLOR env var is set.
    """
    _reconfigure_utf8()
    for attr in ("stdout", "stderr"):
        stream = getattr(sys, attr)
        if stream is None or isinstance(stream, _AnsiStrippingWriter):
            continue
        if not _wants_color(stream):
            setattr(sys, attr, _AnsiStrippingWriter(stream))


def _reconfigure_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
                continue
            except (ValueError, OSError):
                pass
        # Stream can't be reconfigured (already detached, or a capture shim).
        # Best effort: if it exposes a buffer, wrap it; otherwise leave as-is.
        buffer = getattr(stream, "buffer", None)
        if buffer is not None:
            import io

            wrapped = io.TextIOWrapper(buffer, encoding="utf-8", errors="replace", line_buffering=True)
            if stream is sys.stdout:
                sys.stdout = wrapped
            else:
                sys.stderr = wrapped
