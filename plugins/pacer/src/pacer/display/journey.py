"""A journey: named stages run in order under the Pace Line.

Every long operation PACER performs (update, install, release, the checks) is a
journey, so they all look and behave the same. A journey has three renderings
of the same events:

    live     a terminal: header, the Pace Line and one status line, redrawn in
             place thirty times a second, replaced by a ledger when it closes
    plain    anything else: one line per finished stage, nothing redrawn
    events   one JSON object per line, for a parent process to render

The events form is how an update draws one continuous display across two
processes: the parent owns the screen and relays what the child reports.
"""

from __future__ import annotations

import atexit
import json
import math
import os
import sys
import threading
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TextIO

from pacer.display import paceline
from pacer.display.term import (
    HIDE_CURSOR,
    SHOW_CURSOR,
    Caps,
    Pen,
    Region,
    between,
    clip,
    detect,
    visible,
)
from pacer.identity import AGENT

FPS = 30
PROTOCOL = 1
MARGIN = "  "
ENDED = ("done", "skip", "fail")
# A report may also carry `warn` (attention, not failure) and `head` (a group heading).
PLAIN_MARKS = {"done": "ok", "skip": "--", "fail": "!!", "warn": " !"}
INTRO = 0.35  # seconds for the line to unroll
OUTRO_FRAMES = 14


class StepError(RuntimeError):
    """A stage could not finish; the message is shown beside it."""


@dataclass
class Step:
    id: str
    label: str
    expect: float = 3.0  # seconds, used to size the segment and pace the line
    state: str = "pending"  # pending, active, done, skip, fail
    text: str = ""
    began: float = 0.0
    took: float = 0.0


@dataclass
class Outcome:
    """What a stage reports about itself from inside `Journey.step`."""

    journey: Journey
    state: str = "done"
    text: str = ""

    def note(self, text: str) -> None:
        self.journey.note(text)

    def done(self, text: str = "") -> None:
        self.state, self.text = "done", text

    def skip(self, text: str = "") -> None:
        self.state, self.text = "skip", text


class Journey:
    def __init__(
        self,
        title: str,
        steps: Iterable[Step] = (),
        *,
        detail: str = "",
        stream: TextIO | None = None,
        mode: str | None = None,
        env: dict[str, str] | None = None,
    ):
        self.title, self.detail = title, detail
        self.stream = stream if stream is not None else sys.stdout
        env = dict(os.environ) if env is None else env
        caps = detect(self.stream, env)
        wanted = (mode or env.get("PACER_DISPLAY", "")).lower()
        self.mode = "events" if wanted == "events" else "live" if caps.live else "plain"
        if wanted == "plain" or self.mode != "live":
            self.mode = "events" if wanted == "events" else "plain"
            caps = Caps(False, 0, caps.unicode, caps.width)
        self.caps, self.pen = caps, Pen(caps)
        self.glyphs = paceline.UNICODE if caps.unicode else paceline.ASCII
        self.steps: list[Step] = list(steps)
        self.headline, self.hints = "", [""][:0]
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._opened = self._closed = False
        self._shown = 0.0
        self._region = Region(self._write)
        self._headed = False  # plain mode: whether the header line is out
        self._t0 = time.monotonic()

    # -- the caller's side ---------------------------------------------------
    def __enter__(self) -> Journey:
        self.open()
        return self

    def __exit__(self, kind, error, trace) -> None:
        if not self._closed:
            self.close("interrupted" if kind is KeyboardInterrupt else "stopped")

    @property
    def ok(self) -> bool:
        return not any(step.state == "fail" for step in self.steps)

    @property
    def arrow(self) -> str:
        return self.glyphs.arrow

    def open(self) -> None:
        if self._opened:
            return
        self._opened = True
        self._t0 = time.monotonic()
        if self.mode == "events":
            self._emit("plan", steps=[_wire(step) for step in self.steps])
        elif self.mode == "live":
            self._write(HIDE_CURSOR)
            atexit.register(self._restore)
            self._thread = threading.Thread(target=self._loop, name="pacer-journey", daemon=True)
            self._thread.start()

    def plan(self, steps: Iterable[Step]) -> None:
        """Add stages that are not known yet; a known stage keeps its place and state."""
        with self._lock:
            known = {step.id for step in self.steps}
            fresh = [step for step in steps if step.id not in known]
            self.steps += fresh
        if fresh and self.mode == "events" and self._opened:
            self._emit("plan", steps=[_wire(step) for step in fresh])

    def retitle(self, detail: str) -> None:
        with self._lock:
            self.detail = detail

    def begin(self, step_id: str, note: str = "") -> None:
        self.open()
        with self._lock:
            step = self._find(step_id)
            step.state, step.text, step.began = "active", note, time.monotonic()
        if self.mode == "events":
            self._emit("begin", id=step_id, label=step.label, note=note)

    def note(self, text: str) -> None:
        with self._lock:
            active = self._active()
            if active is not None:
                active.text = text
        if self.mode == "events":
            self._emit("note", text=text)

    def end(self, step_id: str, state: str = "done", text: str = "") -> None:
        if state not in ENDED:
            raise ValueError(f"a stage ends as one of {', '.join(ENDED)}")
        self.open()
        with self._lock:
            step = self._find(step_id)
            step.took = time.monotonic() - step.began if step.began else 0.0
            step.state, step.text = state, text
        if self.mode == "events":
            self._emit("end", id=step_id, state=state, text=text)
        elif self.mode == "plain":
            self._plain_header()
            self._write(f"  {PLAIN_MARKS[state]}  {step.label:<14} {text}".rstrip() + "\n")

    @contextmanager
    def step(self, step_id: str, note: str = "") -> Iterator[Outcome]:
        """Run one stage. A StepError or OSError inside it marks the stage failed."""
        self.begin(step_id, note)
        outcome = Outcome(self)
        try:
            yield outcome
        except (StepError, OSError) as error:
            self.end(step_id, "fail", str(error))
        else:
            self.end(step_id, outcome.state, outcome.text)

    def close(self, headline: str = "", hints: Iterable[str] = ()) -> bool:
        """Finish: the live region becomes a ledger. Returns whether every stage held."""
        if self._closed:
            return self.ok
        self._closed = True
        self.headline, self.hints = headline, list(hints)
        if self.mode == "events":
            self._emit("close", headline=headline, hints=self.hints, ok=self.ok)
        elif self.mode == "plain":
            self._plain_header()
            for line in (headline, *self.hints):
                if line:
                    self._write(line + "\n")
        else:
            self._settle()
        return self.ok

    def timings(self) -> dict[str, float]:
        """Seconds each completed stage took, to pace the same journey next time."""
        return {s.id: round(s.took, 2) for s in self.steps if s.state == "done" and s.took > 0}

    def relay(self, line: str) -> dict | None:
        """Apply one event line from a child journey; None when the line is not one."""
        try:
            data = json.loads(line)
        except ValueError:
            return None
        if not isinstance(data, dict) or data.get("journey") != PROTOCOL:
            return None
        event = data.get("event")
        if event == "plan":
            self.plan(
                Step(str(s["id"]), str(s["label"]), float(s.get("expect", 3.0)))
                for s in data.get("steps", [])
            )
        elif event == "begin":
            self.plan([Step(str(data["id"]), str(data.get("label", data["id"])))])
            self.begin(str(data["id"]), str(data.get("note", "")))
        elif event == "note":
            self.note(str(data.get("text", "")))
        elif event == "end":
            self.end(str(data["id"]), str(data.get("state", "done")), str(data.get("text", "")))
        return data

    # -- shared pieces -------------------------------------------------------
    def _find(self, step_id: str) -> Step:
        for step in self.steps:
            if step.id == step_id:
                return step
        raise KeyError(step_id)

    def _active(self) -> Step | None:
        return next((step for step in self.steps if step.state == "active"), None)

    def _write(self, text: str) -> None:
        try:
            self.stream.write(text)
        except UnicodeEncodeError:
            self.stream.write(text.encode("ascii", "replace").decode("ascii"))
        self.stream.flush()

    def _emit(self, event: str, **fields) -> None:
        self._write(json.dumps({"journey": PROTOCOL, "event": event, **fields}) + "\n")

    def _plain_header(self) -> None:
        if self._headed:
            return
        self._headed = True
        self._write(" ".join(part for part in (AGENT, self.title, self.detail) if part) + "\n")

    def _width(self) -> int:
        return max(min(self.caps.width - 4, 76), 30)

    def _header(self) -> str:
        return MARGIN + paceline.signature(
            self.pen, self.glyphs, self.title, self.detail, self._width()
        )

    def _line(self, now: float, *, settled: bool) -> tuple[str, int]:
        width = max(18, min(46, self._width() - 26))
        sizes = paceline.layout([s.expect for s in self.steps], width) or [width]
        failed = {i for i, step in enumerate(self.steps) if step.state == "fail"}
        cells = sum(sizes)
        age = now - self._t0
        reveal = None if settled or age >= INTRO else cells * (1 - (1 - age / INTRO) ** 3)
        line = paceline.render(
            sizes,
            failed,
            self._shown * cells,
            age,
            self.pen,
            self.glyphs,
            settled=settled,
            reveal=reveal,
        )
        return line, width

    # -- live ----------------------------------------------------------------
    def _target(self, now: float) -> float:
        total = sum(step.expect for step in self.steps) or 1.0
        reached = 0.0
        for step in self.steps:
            if step.state in ENDED:
                reached += step.expect
            elif step.state == "active":
                # Approach the end of the segment without arriving until the stage does.
                pace = max(step.expect / 2.0, 0.2)
                reached += step.expect * 0.9 * (1 - math.exp(-(now - step.began) / pace))
        return reached / total

    def _frame(self, now: float) -> list[str]:
        pen, dot = self.pen, self.glyphs.dot
        line, width = self._line(now, settled=False)
        active = self._active()
        room = self._width() - width - 2
        label = pen.bold(active.label) if active else pen.dim("…" if self.caps.unicode else "")
        finished = sum(step.state in ENDED for step in self.steps)
        position = min(finished + 1, len(self.steps))
        counter = f"{position:02d}/{len(self.steps):02d} {dot} {now - self._t0:.1f}s"
        note = clip(active.text if active else "", self._width() - len(counter) - 3)
        return [
            "",
            self._header(),
            f"{MARGIN}{line}  {clip(label, room)}",
            MARGIN + between(pen.dim(note), pen.dim(counter), self._width()),
            "",
        ]

    def _marks(self) -> dict[str, str]:
        pen, glyphs = self.pen, self.glyphs
        return {
            "done": pen.rgb(glyphs.done, paceline.MINT, 92),
            "skip": pen.dim(glyphs.skip),
            "fail": pen.rgb(glyphs.fail, paceline.ALARM, 91, bold=True),
            "warn": pen.rgb(glyphs.warn, paceline.LANTERN, 93, bold=True),
        }

    def _ledger(self, *, with_line: bool = True) -> list[str]:
        pen, glyphs, marks = self.pen, self.glyphs, self._marks()
        column = max((len(step.label) for step in self.steps if step.state != "head"), default=0)
        pad = len(glyphs.done)
        lines = ["", self._header()]
        if with_line:
            line, width = self._line(time.monotonic(), settled=True)
            tone = (paceline.MINT, 92) if self.ok else (paceline.ALARM, 91)
            headline = clip(self.headline, self._width() - width - 2)
            lines.append(f"{MARGIN}{line}  {pen.rgb(headline, *tone, bold=True)}")
        lines.append("")
        for index, step in enumerate(self.steps):
            if step.state == "head":
                if index:
                    lines.append("")
                lines.append(MARGIN + pen.dim(step.label))
                continue
            if step.state not in ENDED and step.state != "warn" and self.ok:
                continue
            mark = marks.get(step.state, " " * pad)
            mark += " " * (pad - visible(mark))
            text = step.text if step.state in ENDED or step.state == "warn" else "not run"
            text = clip(text, self._width() - column - pad - 3)
            if step.state != "done":
                text = pen.dim(text)
            lines.append(f"{MARGIN}{mark} {step.label:<{column}}  {text}".rstrip())
        if self.hints:
            lines.append("")
            lines += [MARGIN + pen.dim(clip(hint, self._width())) for hint in self.hints]
        return [*lines, ""]

    def _loop(self) -> None:
        last = time.monotonic()
        while not self._stop.wait(1 / FPS):
            now = time.monotonic()
            with self._lock:
                self._ease(self._target(now), now - last)
                self._draw(self._frame(now))
            last = now

    def _ease(self, target: float, elapsed: float) -> None:
        self._shown += (target - self._shown) * (1 - math.exp(-elapsed / 0.15))

    def _draw(self, lines: list[str], *, final: bool = False) -> None:
        self._region.draw(lines, final=final)

    def _settle(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
        with self._lock:
            if self.ok and self._opened:
                for _ in range(OUTRO_FRAMES):  # the line runs out to its end
                    self._shown += (1.0 - self._shown) * 0.4
                    self._draw(self._frame(time.monotonic()))
                    time.sleep(1 / FPS)
                self._shown = 1.0
            self._draw(self._ledger(), final=True)
        self._restore()

    def _restore(self) -> None:
        if self.mode == "live" and self._opened:
            self._write(SHOW_CURSOR)
            atexit.unregister(self._restore)


def _wire(step: Step) -> dict:
    return {"id": step.id, "label": step.label, "expect": step.expect}


def report(
    title: str,
    rows: Iterable[tuple[str, str, str]],
    *,
    detail: str = "",
    hints: Iterable[str] = (),
    stream: TextIO | None = None,
) -> bool:
    """A finished ledger with no line. True when no row failed.

    `rows` are (state, label, text): `done`, `skip`, `fail`, `warn` for attention
    short of failure, or `head` for a group heading above the rows that follow.
    """
    journey = Journey(title, detail=detail, stream=stream)
    journey.steps = [Step(label, label, state=state, text=text) for state, label, text in rows]
    journey.hints = list(hints)
    if journey.mode == "live":
        journey._write("\n".join(journey._ledger(with_line=False)) + "\n")
    else:
        journey._plain_header()
        for index, step in enumerate(journey.steps):
            if step.state == "head":
                journey._write(("\n" if index else "") + f"{step.label}\n")
                continue
            mark = PLAIN_MARKS.get(step.state, "  ")
            journey._write(f"  {mark}  {step.label:<14} {step.text}".rstrip() + "\n")
        for hint in journey.hints:
            journey._write(hint + "\n")
    return journey.ok
