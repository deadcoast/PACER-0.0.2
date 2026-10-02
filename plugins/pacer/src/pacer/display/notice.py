"""The update notice: three lines, shown once for each new version.

    PACER 3.1.0 is available · installed 3.0.0
      update    pacer update
      silence   pacer update --notify off

One wording for both places it can appear: a terminal, where it is styled, and
an agent session, where the host shows plain text to the person and not to the model.
"""

from __future__ import annotations

from typing import TextIO

from pacer.display import paceline
from pacer.display.term import Pen, detect
from pacer.identity import AGENT

UPDATE = "pacer update"
SILENCE = "pacer update --notify off"


def text(current: str, latest: str) -> str:
    """The notice without styling, for a host to show."""
    return (
        f"{AGENT} {latest} is available · installed {current}\n"
        f"  update    {UPDATE}\n"
        f"  silence   {SILENCE}"
    )


def styled(current: str, latest: str, stream: TextIO) -> str:
    """The notice for a terminal, degraded to what `stream` can show."""
    caps = detect(stream)
    pen = Pen(caps)
    glyphs = paceline.UNICODE if caps.unicode else paceline.ASCII
    lantern = pen.rgb("●" if caps.unicode else "*", paceline.LANTERN, 93)
    head = f"{pen.bold(f'{AGENT} {latest}')} is available"
    return "\n".join(
        [
            "",
            f"  {lantern} {head} {pen.dim(f'{glyphs.dot} installed {current}')}",
            f"    {pen.dim('update ')}   {UPDATE}",
            f"    {pen.dim('silence')}   {SILENCE}",
            "",
        ]
    )
