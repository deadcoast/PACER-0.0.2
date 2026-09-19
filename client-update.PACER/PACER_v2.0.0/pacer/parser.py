from __future__ import annotations
import re
from pathlib import Path
from .model import Plan, Global, Phase, Pace

_Q = r'"([^"]*)"'

def _attr(line: str, key: str, default: str = "") -> str:
    m = re.search(rf"\b{re.escape(key)}=(?:\"([^\"]*)\"|([^\s]+))", line)
    if not m:
        return default
    return m.group(1) if m.group(1) is not None else m.group(2)

def parse(path: str | Path) -> Plan:
    plan = Plan()
    g = None
    p = None
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        if line.startswith("PROJECT "):
            m = re.search(_Q, line)
            if m: plan.project = m.group(1)
            plan.maturity = _attr(line, "maturity", plan.maturity)
        elif line.startswith("MODULATION "):
            m = re.search(_Q, line)
            if m: plan.modulation = m.group(1)
        elif line.startswith("GLOBAL "):
            m = re.match(rf"GLOBAL\s+(\S+)\s+{_Q}", line)
            if m:
                g = Global(m.group(1), m.group(2), _attr(line, "state", "todo"))
                plan.globals.append(g)
                p = None
        elif line.startswith("PHASE "):
            m = re.match(rf"PHASE\s+(\S+)\s+{_Q}", line)
            if m and g:
                p = Phase(m.group(1), m.group(2), _attr(line, "state", "todo"))
                g.phases.append(p)
        elif line.startswith("PACE "):
            m = re.match(rf"PACE\s+(\S+)\s+{_Q}", line)
            if m and p:
                p.paces.append(Pace(m.group(1), m.group(2), _attr(line, "state", "todo")))
        elif line.startswith("SOURCE "):
            m = re.search(_Q, line)
            if m:
                (p.sources if p else g.sources if g else []).append(m.group(1))
        elif line.startswith("EXIT ") and p:
            p.exit = _attr(line, "coherent", "")
        elif line.startswith("GATE ") and p:
            kind = line.split()[1] if len(line.split()) > 1 else "unknown"
            p.gates.append((kind, _attr(line, "reason", "")))
        elif line == ":loop⠁:":
            plan.has_loop = True
    return plan
