"""The work tree as indented cards.

Not a second grammar: each line is the row's ordinary card, indented by its depth
in the AREA / PHASE / PACE tree.
"""

from __future__ import annotations

from pacer.cards import card
from pacer.schema import pos_key, pos_parts


def render_tree(tables: dict, config: dict) -> str:
    lines = [f"PACER {config['project']} tier={config['tier']}"]
    for row in sorted(tables["todo"], key=pos_key):
        try:
            depth = sum(part is not None for part in pos_parts(row["Pos"])) - 1
        except ValueError:
            depth = 0
        lines.append("  " * depth + card("todo", row))
    return "\n".join(lines)
