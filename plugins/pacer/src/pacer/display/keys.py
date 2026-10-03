"""Keys from the console, one at a time, without echo.

A prompt asks for the next key and gets either a name from the list below, a
printable character, or None when nothing arrived before its timeout. The
timeout is what lets a prompt animate while it waits. `Terminal` reads the
real console; a prompt accepts any source with the same `read`, so the tests
drive one with a script.

Standard library only: `msvcrt` on Windows, `termios` elsewhere.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Iterable
from typing import Protocol, TextIO

UP, DOWN, LEFT, RIGHT = "up", "down", "left", "right"
HOME, END, DELETE, BACKSPACE = "home", "end", "delete", "backspace"
ENTER, TAB, ESC = "enter", "tab", "esc"
NAMED = frozenset({UP, DOWN, LEFT, RIGHT, HOME, END, DELETE, BACKSPACE, ENTER, TAB, ESC})

COMMON = {"\r": ENTER, "\n": ENTER, "\t": TAB, "\x1b": ESC, "\x08": BACKSPACE, "\x7f": BACKSPACE}
WINDOWS = {"H": UP, "P": DOWN, "K": LEFT, "M": RIGHT, "G": HOME, "O": END, "S": DELETE}
SEQUENCES = {
    b"[A": UP,
    b"[B": DOWN,
    b"[C": RIGHT,
    b"[D": LEFT,
    b"[H": HOME,
    b"[F": END,
    b"[1~": HOME,
    b"[7~": HOME,
    b"[4~": END,
    b"[8~": END,
    b"[3~": DELETE,
    b"OA": UP,
    b"OB": DOWN,
    b"OC": RIGHT,
    b"OD": LEFT,
    b"OH": HOME,
    b"OF": END,
}


class Keys(Protocol):
    def read(self, timeout: float | None = None) -> str | None:
        """The next key, or None when `timeout` seconds pass without one."""


class Scripted:
    """Keys from a list; None entries are quiet ticks. Past the end it cancels."""

    def __init__(self, keys: Iterable[str | None]):
        self._keys = iter(keys)

    def read(self, timeout: float | None = None) -> str | None:
        return next(self._keys, ESC)


def available(stdin: TextIO | None = None, stdout: TextIO | None = None) -> bool:
    """Whether a prompt may be shown: both standard streams are terminals."""
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    try:
        return bool(stdin.isatty() and stdout.isatty())
    except (AttributeError, ValueError):
        return False


class Terminal:
    """Raw reads from the console. Use as a context manager: it restores the terminal."""

    def __init__(self, stream: TextIO | None = None):
        self.stream = sys.stdin if stream is None else stream
        self._saved: list | None = None

    def __enter__(self) -> Terminal:
        if sys.platform != "win32":
            import termios
            import tty

            descriptor = self.stream.fileno()
            self._saved = termios.tcgetattr(descriptor)
            tty.setcbreak(descriptor)
        return self

    def __exit__(self, *_: object) -> None:
        if sys.platform == "win32":
            return
        if self._saved is not None:
            import termios

            termios.tcsetattr(self.stream.fileno(), termios.TCSADRAIN, self._saved)
            self._saved = None

    def read(self, timeout: float | None = None) -> str | None:
        key = self._read_windows(timeout) if sys.platform == "win32" else self._read_posix(timeout)
        if key == "\x03":
            raise KeyboardInterrupt
        return key

    def _read_windows(self, timeout: float | None) -> str | None:
        import msvcrt

        deadline = None if timeout is None else time.monotonic() + timeout
        while not msvcrt.kbhit():
            if deadline is not None and time.monotonic() >= deadline:
                return None
            time.sleep(0.01)
        char = msvcrt.getwch()
        if char in ("\x00", "\xe0"):
            return WINDOWS.get(msvcrt.getwch(), "")
        return COMMON.get(char, char)

    def _read_posix(self, timeout: float | None) -> str | None:
        import select

        descriptor = self.stream.fileno()
        ready, _, _ = select.select([descriptor], [], [], timeout)
        if not ready:
            return None
        first = os.read(descriptor, 1)
        if first == b"\x1b":
            # A sequence follows at once; the escape key alone comes with nothing after it.
            sequence = b""
            while len(sequence) < 8 and select.select([descriptor], [], [], 0.03)[0]:
                sequence += os.read(descriptor, 1)
            return SEQUENCES.get(sequence, ESC) if sequence else ESC
        data = first
        while _continues(data) and select.select([descriptor], [], [], 0.03)[0]:
            data += os.read(descriptor, 1)
        char = data.decode("utf-8", "replace")
        return COMMON.get(char, char)


def _continues(data: bytes) -> bool:
    """Whether a UTF-8 sequence is still missing continuation bytes."""
    lead = data[0]
    needed = (
        2 if lead >> 5 == 0b110 else 3 if lead >> 4 == 0b1110 else 4 if lead >> 3 == 0b11110 else 1
    )
    return len(data) < needed
