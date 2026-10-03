"""What the terminal can do, and a pen that never asks for more than that.

Three questions decide every byte PACER prints: may the cursor move (`live`),
how many colours are there (`color`: 0, 4, 8 or 24 bits), and can the font be
trusted with box-drawing and check marks (`unicode`). Off a terminal the answer
to all three is no, and output is plain lines a log can keep.

`PACER_DISPLAY` forces a mode: `live`, `plain` or `events`. `NO_COLOR` is honoured.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import TextIO

RGB = tuple[int, int, int]
SGR = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
RESET = "\x1b[0m"
MODES = ("live", "plain", "events")
HIDE_CURSOR, SHOW_CURSOR = "\x1b[?25l", "\x1b[?25h"


@dataclass(frozen=True)
class Caps:
    live: bool
    color: int
    unicode: bool
    width: int


def _enable_vt(stream: TextIO) -> bool:
    """Turn on escape-sequence processing for a Windows console; False when it has none."""
    if sys.platform != "win32":
        return True
    try:
        descriptor = stream.fileno()
    except (OSError, ValueError, AttributeError):
        return True  # not a console handle; nothing to switch on
    try:
        import ctypes
        import msvcrt

        kernel = ctypes.windll.kernel32
        handle = msvcrt.get_osfhandle(descriptor)
        mode = ctypes.c_uint32()
        if not kernel.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel.SetConsoleMode(handle, mode.value | 0x0004))
    except (OSError, ValueError, AttributeError):
        return False


def _depth(env: dict[str, str]) -> int:
    if env.get("COLORTERM", "").lower() in {"truecolor", "24bit"} or env.get("WT_SESSION"):
        return 24
    if env.get("TERM_PROGRAM") in {"vscode", "iTerm.app", "WezTerm", "ghostty", "Hyper"}:
        return 24
    if sys.platform == "win32":
        return 24  # every console that accepts escape sequences accepts 24-bit colour
    return 8 if "256" in env.get("TERM", "") else 4


def detect(stream: TextIO, env: dict[str, str] | None = None) -> Caps:
    env = dict(os.environ) if env is None else env
    forced = env.get("PACER_DISPLAY", "").lower()
    width = shutil.get_terminal_size((100, 24)).columns
    encoding = (getattr(stream, "encoding", "") or "").lower()
    unicode = "utf" in encoding
    if forced == "live":
        return Caps(True, 0 if env.get("NO_COLOR") else 24, True, width)
    tty = hasattr(stream, "isatty") and stream.isatty()
    live = tty and forced not in {"plain", "events"} and env.get("TERM") != "dumb"
    live = live and _enable_vt(stream)
    if not live:
        return Caps(False, 0, unicode, width)
    return Caps(True, 0 if env.get("NO_COLOR") else _depth(env), unicode, width)


class Pen:
    """Colour and weight, degraded to what the terminal has."""

    def __init__(self, caps: Caps):
        self.caps = caps

    def rgb(self, text: str, color: RGB, basic: int = 37, *, bold: bool = False) -> str:
        """`color` on a 24-bit terminal, its nearest cube colour on 256, `basic` on 16."""
        depth = self.caps.color
        if not text or depth == 0:
            return self.bold(text) if bold else text
        r, g, b = color
        if depth == 24:
            code = f"38;2;{r};{g};{b}"
        elif depth == 8:
            code = f"38;5;{16 + 36 * round(r / 51) + 6 * round(g / 51) + round(b / 51)}"
        else:
            code = str(basic)
        return f"\x1b[{'1;' if bold else ''}{code}m{text}{RESET}"

    def bold(self, text: str) -> str:
        return f"\x1b[1m{text}{RESET}" if text and self.caps.live else text

    def dim(self, text: str) -> str:
        return f"\x1b[2m{text}{RESET}" if text and self.caps.live else text


class Region:
    """A block of lines redrawn in place: the live form of every PACER display.

    Each draw replaces the previous one. Frames are wrapped in synchronised-output
    marks so a terminal that honours them never shows a half-drawn frame.
    """

    def __init__(self, write: Callable[[str], None]):
        self.write, self.height = write, 0

    def draw(self, lines: list[str], *, final: bool = False) -> None:
        out = ["\x1b[?2026h"]
        if self.height:
            out.append(f"\x1b[{self.height}A")
        if final:
            out.append("\r\x1b[J")
        out += [f"\r\x1b[2K{line}\n" for line in lines]
        out.append("\x1b[?2026l")
        self.write("".join(out))
        self.height = len(lines)


def visible(text: str) -> int:
    """Columns a string occupies once escape sequences are removed."""
    return len(SGR.sub("", text))


def clip(text: str, width: int, ellipsis: str = "…") -> str:
    """Shorten to `width` columns without cutting an escape sequence in half."""
    if visible(text) <= width:
        return text
    out, shown, position = [], 0, 0
    room = max(width - len(ellipsis), 0)
    while position < len(text) and shown < room:
        match = SGR.match(text, position)
        if match:
            out.append(match.group())
            position = match.end()
            continue
        out.append(text[position])
        shown += 1
        position += 1
    styled = "\x1b[" in text
    return "".join(out).rstrip() + ellipsis + (RESET if styled else "")


def between(left: str, right: str, width: int) -> str:
    """`left` and `right` at the edges of `width` columns; `right` goes when it cannot fit."""
    gap = width - visible(left) - visible(right)
    return left + " " * gap + right if gap >= 2 else clip(left, width)
