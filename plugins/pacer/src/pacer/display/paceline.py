"""The Pace Line: PACER's progress display.

One line, cut into segments: one per stage, each as long as the stage is
expected to take, so the line advances at an even pace. The drawn part runs
from night indigo to ice. Its leading edge carries a lantern: a warm point that
breathes, and a glint of the same light that travels the drawn line from its
start to the edge, again and again, while work is in progress. When the last
stage ends the line is complete and the light is gone.

This module is a pure function from state to one string. The journey decides
the state and the clock.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from pacer.display.term import RGB, Pen, between
from pacer.identity import AGENT, LINEAGE

NIGHT: RGB = (104, 92, 230)
DUSK: RGB = (62, 136, 255)
ICE: RGB = (96, 208, 255)
LANTERN: RGB = (255, 200, 87)
TRACK: RGB = (92, 97, 115)
ALARM: RGB = (255, 92, 92)
MINT: RGB = (61, 214, 140)
WHITE: RGB = (255, 255, 255)

GLINT_PERIOD = 1.5  # seconds for the glint to travel the drawn line
GLINT_SPREAD = 1.8  # cells
BREATH = 1.1  # lantern pulses per second


@dataclass(frozen=True)
class Glyphs:
    line: str
    half: str
    track: str
    done: str
    skip: str
    fail: str
    warn: str
    arrow: str
    dot: str
    ellipsis: str
    caret: str


UNICODE = Glyphs("━", "╸", "─", "✓", "·", "✗", "!", "▸", "·", "…", "▏")
ASCII = Glyphs("=", ">", "-", "ok", "--", "!!", " !", "->", "/", "...", "|")


def mix(a: RGB, b: RGB, t: float) -> RGB:
    t = min(max(t, 0.0), 1.0)
    return (
        round(a[0] + (b[0] - a[0]) * t),
        round(a[1] + (b[1] - a[1]) * t),
        round(a[2] + (b[2] - a[2]) * t),
    )


def gradient(x: float) -> RGB:
    """Night to dusk to ice, for x from 0 to 1."""
    x = min(max(x, 0.0), 1.0)
    return mix(NIGHT, DUSK, x * 2) if x < 0.5 else mix(DUSK, ICE, x * 2 - 1)


def wordmark(pen: Pen) -> str:
    """The agent's name, each letter a step along the gradient."""
    last = max(len(AGENT) - 1, 1)
    return "".join(
        pen.rgb(letter, gradient(i / last), 94, bold=True) for i, letter in enumerate(AGENT)
    )


def signature(pen: Pen, glyphs: Glyphs, title: str, detail: str, width: int) -> str:
    """The header every display opens with: wordmark, title and detail; the lineage at the right."""
    dot = glyphs.dot
    left = f"{wordmark(pen)}  {pen.dim(title)}"
    if detail:
        left += f" {pen.dim(dot)} {detail}"
    return between(left, pen.dim(f" {dot} ".join(LINEAGE)), width)


def rail(pen: Pen, glyphs: Glyphs, color: RGB, cells: int, clock: float | None = None) -> str:
    """A short line in one colour; with a clock its last cell breathes like the lantern."""
    if clock is None:
        return pen.rgb(glyphs.line * cells, color, 94)
    breath = 0.5 + 0.5 * math.sin(clock * 2 * math.pi * BREATH)
    body = pen.rgb(glyphs.line * (cells - 1), color, 94)
    return body + pen.rgb(glyphs.line, mix(color, WHITE, 0.15 + 0.45 * breath), 97)


def layout(weights: list[float], width: int) -> list[int]:
    """Cells per segment: proportional to weight, at least two, one gap between segments."""
    count = len(weights)
    if count == 0:
        return []
    cells = max(width - (count - 1), count)
    floor = 2 if cells >= 2 * count else 1
    total = sum(weights) or 1.0
    exact = [w / total * cells for w in weights]
    sizes = [max(floor, int(e)) for e in exact]
    while sum(sizes) > cells:
        widest = max(range(count), key=lambda i: sizes[i])
        sizes[widest] -= 1
    while sum(sizes) < cells:
        neediest = max(range(count), key=lambda i: exact[i] - sizes[i])
        sizes[neediest] += 1
    return sizes


def render(
    sizes: list[int],
    failed: set[int],
    fill: float,
    clock: float,
    pen: Pen,
    glyphs: Glyphs,
    *,
    settled: bool = False,
    reveal: float | None = None,
) -> str:
    """The line with `fill` cells drawn. `failed` holds indexes of segments that stopped."""
    total = sum(sizes)
    glint = (clock % GLINT_PERIOD) / GLINT_PERIOD * (fill + 8) - 4
    breath = 0.5 + 0.5 * math.sin(clock * 2 * math.pi * BREATH)
    out: list[str] = []
    cell = 0
    for index, size in enumerate(sizes):
        if index:
            out.append(" ")
        for _ in range(size):
            if reveal is not None and cell >= reveal:
                out.append(" ")
            elif index in failed:
                out.append(pen.rgb(glyphs.line, ALARM, 91))
            elif cell + 1 <= fill + 1e-9:
                color = gradient(cell / max(total - 1, 1))
                if not settled:
                    glow = math.exp(-(((cell + 0.5 - glint) / GLINT_SPREAD) ** 2))
                    color = mix(color, LANTERN, 0.9 * glow)
                    if cell + 2 > fill:  # the leading full cell carries the lantern
                        color = mix(color, LANTERN, 0.55 + 0.4 * breath)
                out.append(pen.rgb(glyphs.line, color, 94))
            elif cell + 0.5 <= fill and not settled:
                out.append(pen.rgb(glyphs.half, mix(LANTERN, (255, 255, 255), 0.25 * breath), 93))
            else:
                out.append(pen.rgb(glyphs.track, TRACK, 90))
            cell += 1
    return "".join(out)
