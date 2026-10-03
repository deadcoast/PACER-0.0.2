"""Questions asked in the terminal, in the Pace Line's idiom.

Two prompts: a chooser, where each option sits on a short rail and the chosen
one is lit; and a field for a path, scanned as it is typed so the answer is
known before it is given. Both animate while they wait, collapse to one ledger
line once answered, and are only ever shown when both standard streams are a
terminal. Anywhere else each returns its default at once, so an agent or a
script running the same command is never asked anything.

    choose("update", "where?", [Option("claude", "Claude Code"), ...])
    ask_path("init", "where?", default=Path.cwd(), scan=describe)
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from pacer.display import paceline
from pacer.display.keys import (
    BACKSPACE,
    DELETE,
    DOWN,
    END,
    ENTER,
    ESC,
    HOME,
    LEFT,
    NAMED,
    RIGHT,
    TAB,
    UP,
    Keys,
    Terminal,
    available,
)
from pacer.display.term import HIDE_CURSOR, SHOW_CURSOR, Pen, Region, clip, detect

FPS = 24
MARGIN = "  "
RAIL = 7  # cells of rail beside each option
TONES = {"good": paceline.MINT, "warn": paceline.LANTERN, "bad": paceline.ALARM}


@dataclass
class Option:
    key: str
    label: str
    text: str = ""  # shown dim beside the label: a version, a state


@dataclass
class Scan:
    """What a field knows about the path typed so far."""

    state: str = "good"  # good | warn | bad
    notes: list[str] = field(default_factory=list)


class Prompt:
    """The frame loop, the header and the closing line shared by every prompt."""

    def __init__(
        self,
        title: str,
        question: str,
        *,
        stream: TextIO | None = None,
        env: dict[str, str] | None = None,
    ):
        self.title, self.question = title, question
        self.stream = sys.stdout if stream is None else stream
        env = dict(os.environ) if env is None else env
        self.caps = detect(self.stream, env)
        self.live = self.caps.live and env.get("PACER_DISPLAY", "").lower() != "plain"
        self.pen = Pen(self.caps)
        self.glyphs = paceline.UNICODE if self.caps.unicode else paceline.ASCII
        self.region = Region(self._write)
        self.flash = ""  # a short message in place of the legend, cleared on the next key
        self._t0 = time.monotonic()

    # -- for subclasses ------------------------------------------------------
    def frame(self, now: float) -> list[str]:
        raise NotImplementedError

    def handle(self, key: str) -> str | None:
        """Apply one key; "accept" or "cancel" ends the prompt."""
        raise NotImplementedError

    def answer(self) -> str:
        """The text shown on the closing line once accepted."""
        raise NotImplementedError

    # -- the loop ------------------------------------------------------------
    def run(self, keys: Keys | None) -> bool:
        """Draw, read, repeat. True when accepted."""
        source: Keys = Terminal() if keys is None else keys
        self._write(HIDE_CURSOR)
        verdict = "cancel"
        try:
            with ExitStack() as stack:
                if isinstance(source, Terminal):
                    stack.enter_context(source)
                while True:
                    self.region.draw(self.frame(time.monotonic()))
                    key = source.read(1 / FPS)
                    if key is None:
                        continue
                    self.flash = ""
                    outcome = self.handle(key)
                    if outcome in ("accept", "cancel"):
                        verdict = outcome
                        break
        finally:
            self.region.draw(self.closing(verdict == "accept"), final=True)
            self._write(SHOW_CURSOR)
        return verdict == "accept"

    def closing(self, accepted: bool) -> list[str]:
        pen, glyphs = self.pen, self.glyphs
        if accepted:
            mark = pen.rgb(glyphs.done, paceline.MINT, 92)
            text = self.fit(self.answer(), self.width() - 4)
        else:
            mark, text = pen.dim(glyphs.skip), pen.dim("cancelled")
        return ["", self.header(), f"{MARGIN}{mark} {text}", ""]

    def fit(self, text: str, room: int) -> str:
        """Shorten an answer for the closing line; a prompt whose answer ends matter overrides."""
        return clip(text, room)

    # -- pieces --------------------------------------------------------------
    def width(self) -> int:
        return max(min(self.caps.width - 4, 76), 30)

    def header(self) -> str:
        return MARGIN + paceline.signature(
            self.pen, self.glyphs, self.title, self.question, self.width()
        )

    def legend(self, text: str) -> str:
        shown = self.flash or text
        return MARGIN + (
            self.pen.rgb(shown, paceline.LANTERN, 93) if self.flash else self.pen.dim(shown)
        )

    def _write(self, text: str) -> None:
        try:
            self.stream.write(text)
        except UnicodeEncodeError:
            self.stream.write(text.encode("ascii", "replace").decode("ascii"))
        self.stream.flush()


# -- the chooser ---------------------------------------------------------------
class Chooser(Prompt):
    def __init__(self, title: str, question: str, options: list[Option], default: int, **kw):
        super().__init__(title, question, **kw)
        if not options:
            raise ValueError("a chooser needs at least one option")
        self.options = options
        self.selected = max(0, min(default, len(options) - 1))

    def frame(self, now: float) -> list[str]:
        pen, glyphs = self.pen, self.glyphs
        column = max(len(option.label) for option in self.options)
        clock = now - self._t0
        rows = []
        for index, option in enumerate(self.options):
            chosen = index == self.selected
            if chosen:
                line = paceline.render([RAIL], set(), RAIL, clock, pen, glyphs)
                mark = pen.rgb(glyphs.arrow, paceline.LANTERN, 93)
                label = pen.bold(option.label)
            else:
                line = pen.rgb(glyphs.track * RAIL, paceline.TRACK, 90)
                mark, label = " " * len(glyphs.arrow), option.label
            label += " " * (column - len(option.label))
            text = pen.dim(option.text) if option.text else ""
            rows.append(f"{MARGIN}{mark} {line}  {label}  {text}".rstrip())
        count = len(self.options)
        keys = f"1{'–' if self.caps.unicode else '-'}{count}" if count > 1 else "1"
        arrows = "↑↓" if self.caps.unicode else "up/down"
        legend = self.legend(f"{arrows} or {keys}  {glyphs.dot}  enter chooses  {glyphs.dot}  esc")
        return ["", self.header(), "", *rows, "", legend]

    def handle(self, key: str) -> str | None:
        count = len(self.options)
        if key in (UP, "k"):
            self.selected = (self.selected - 1) % count
        elif key in (DOWN, TAB, "j"):
            self.selected = (self.selected + 1) % count
        elif key in (ENTER, " "):
            return "accept"
        elif key in (ESC, "q"):
            return "cancel"
        elif key.isdigit() and 1 <= int(key) <= count:
            self.selected = int(key) - 1
            return "accept"
        return None

    def answer(self) -> str:
        return self.options[self.selected].label


def choose(
    title: str,
    question: str,
    options: list[Option],
    *,
    default: int = 0,
    stream: TextIO | None = None,
    keys: Keys | None = None,
    env: dict[str, str] | None = None,
) -> str | None:
    """The key of the chosen option; the default's key off a terminal; None when cancelled."""
    chooser = Chooser(title, question, options, default, stream=stream, env=env)
    if not chooser.live or (keys is None and not available(stdout=chooser.stream)):
        return options[chooser.selected].key
    return options[chooser.selected].key if chooser.run(keys) else None


# -- the path field -------------------------------------------------------------
class Field(Prompt):
    def __init__(
        self, title: str, question: str, default: Path, scan: Callable[[Path | None], Scan], **kw
    ):
        super().__init__(title, question, **kw)
        self.default, self.scan = default, scan
        self.text, self.cursor = "", 0
        self.result = scan(None)  # None: the default, nothing typed yet

    # -- editing -------------------------------------------------------------
    def value(self) -> Path | None:
        """The path typed so far, or None while the field is empty."""
        return Path(os.path.expanduser(self.text)) if self.text.strip() else None

    def chosen(self) -> Path:
        return self.value() or self.default

    def _changed(self) -> None:
        self.result = self.scan(self.value())

    def insert(self, chars: str) -> None:
        self.text = self.text[: self.cursor] + chars + self.text[self.cursor :]
        self.cursor += len(chars)
        self._changed()

    def complete(self) -> None:
        """Extend the last component to the directories that match it."""
        text = os.path.expanduser(self.text) if self.text else ""
        head, tail = (text, "") if text.endswith(("/", "\\")) else os.path.split(text)
        base = Path(head) if head else Path.cwd()
        try:
            names = sorted(e.name for e in os.scandir(base) if e.is_dir())
        except OSError:
            return
        found = [n for n in names if n.lower().startswith(tail.lower())]
        if not found:
            self.flash = "nothing matches"
            return
        if len(found) == 1:
            stem = found[0] + os.sep
        else:
            stem = _common(found)
            self.flash = (
                f"{len(found)} match: " + ", ".join(found[:4]) + ("…" if len(found) > 4 else "")
            )
        root = text if text.endswith(("/", "\\")) else (head + os.sep if head else "")
        self.text = root + stem
        self.cursor = len(self.text)
        self._changed()

    # -- the prompt ----------------------------------------------------------
    def frame(self, now: float) -> list[str]:
        pen, glyphs = self.pen, self.glyphs
        clock = now - self._t0
        caret = pen.rgb(glyphs.caret, paceline.mix(paceline.LANTERN, paceline.WHITE, 0.3), 93)
        room = self.width() - 4
        if self.text:
            shown, at = _window(self.text, self.cursor, room)
            typed = shown[:at] + caret + shown[at:]
        else:
            typed = caret + pen.dim(clip(str(self.default), room - 1))
        tone = TONES.get(self.result.state, paceline.MINT)
        rail = paceline.rail(pen, glyphs, tone, RAIL, clock)
        notes = pen.dim(clip(f" {glyphs.dot} ".join(self.result.notes), self.width() - RAIL - 5))
        mark = pen.rgb(glyphs.arrow, paceline.LANTERN, 93)
        legend = self.legend(
            f"type a path  {glyphs.dot}  tab completes  {glyphs.dot}  enter accepts  "
            f"{glyphs.dot}  esc"
        )
        field_line = f"{MARGIN}{mark} {typed}"
        scan_line = f"{MARGIN}  {rail}  {notes}".rstrip()
        return ["", self.header(), "", field_line, scan_line, "", legend]

    def handle(self, key: str) -> str | None:
        if key == ENTER:
            if self.result.state == "bad":
                self.flash = self.result.notes[0] if self.result.notes else "not a usable path"
                return None
            return "accept"
        if key == ESC:
            return "cancel"
        if key == TAB:
            self.complete()
        elif key == BACKSPACE:
            if self.cursor:
                self.text = self.text[: self.cursor - 1] + self.text[self.cursor :]
                self.cursor -= 1
                self._changed()
        elif key == DELETE:
            self.text = self.text[: self.cursor] + self.text[self.cursor + 1 :]
            self._changed()
        elif key == LEFT:
            self.cursor = max(0, self.cursor - 1)
        elif key == RIGHT:
            self.cursor = min(len(self.text), self.cursor + 1)
        elif key == HOME:
            self.cursor = 0
        elif key == END:
            self.cursor = len(self.text)
        elif key == "\x15":  # ctrl-u: start over
            self.text, self.cursor = "", 0
            self._changed()
        elif key == "\x17":  # ctrl-w: drop the last component
            kept = self.text[: self.cursor].rstrip("/\\")
            cut = max(kept.rfind("/"), kept.rfind("\\")) + 1
            self.text = self.text[:cut] + self.text[self.cursor :]
            self.cursor = cut
            self._changed()
        elif key not in NAMED and key.isprintable():
            self.insert(key)
        return None

    def answer(self) -> str:
        return str(self.chosen())

    def fit(self, text: str, room: int) -> str:
        # A path is read from its end: keep the tail.
        return text if len(text) <= room else "…" + text[-(room - 1) :]


def ask_path(
    title: str,
    question: str,
    *,
    default: Path,
    scan: Callable[[Path | None], Scan],
    stream: TextIO | None = None,
    keys: Keys | None = None,
    env: dict[str, str] | None = None,
) -> Path | None:
    """A directory typed in the terminal; the default off one; None when cancelled."""
    prompt = Field(title, question, default, scan, stream=stream, env=env)
    if not prompt.live or (keys is None and not available(stdout=prompt.stream)):
        return default
    return prompt.chosen() if prompt.run(keys) else None


def _common(names: list[str]) -> str:
    """The longest prefix the names share, compared without case, in the first name's case."""
    first = names[0]
    length = 0
    while length < len(first) and all(
        n[: length + 1].lower() == first[: length + 1].lower() for n in names
    ):
        length += 1
    return first[:length]


def _window(text: str, cursor: int, room: int) -> tuple[str, int]:
    """The part of `text` that fits in `room` columns with the cursor in view."""
    if len(text) <= room:
        return text, cursor
    span = room - 2
    start = 0 if cursor <= span else cursor - span
    shown = text[start : start + span]
    prefix = "…" if start else ""
    suffix = "…" if start + span < len(text) else ""
    return prefix + shown + suffix, cursor - start + len(prefix)
