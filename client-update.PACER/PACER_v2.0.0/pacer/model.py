from __future__ import annotations
from dataclasses import dataclass, field

@dataclass
class Pace:
    id: str
    title: str
    state: str = "todo"

@dataclass
class Phase:
    id: str
    title: str
    state: str = "todo"
    paces: list[Pace] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    exit: str = ""
    gates: list[tuple[str, str]] = field(default_factory=list)

@dataclass
class Global:
    id: str
    title: str
    state: str = "todo"
    phases: list[Phase] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

@dataclass
class Plan:
    project: str = "UNSET"
    maturity: str = "prototype"
    modulation: str = ""
    globals: list[Global] = field(default_factory=list)
    has_loop: bool = False
