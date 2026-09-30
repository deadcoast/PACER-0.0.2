"""Typed operations for MCP tool schemas."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class Command(BaseModel):
    """Disallow misspelled operation fields at the transport boundary."""

    model_config = ConfigDict(extra="forbid")


class Add(Command):
    op: Literal["add"]
    register_name: Literal["todo", "overlord", "organism", "nodule", "decision"] = Field(
        alias="register"
    )
    row: dict[str, str]


class Set(Command):
    op: Literal["set"]
    id: str
    fields: dict[str, str]


class Link(Command):
    op: Literal["link"]
    id: str
    field: str
    target: str
    remove: bool = False


class Move(Command):
    op: Literal["move"]
    id: str
    pos: str


class Status(Command):
    op: Literal["status"]
    id: str
    status: Literal[
        "TODO",
        "ACTIVE",
        "INTEGRATED",
        "DONE",
        "SCAFFOLD",
        "PACED_REQUIREMENT",
        "VALIDATED_COMPLETE",
    ]


class Latch(Command):
    op: Literal["latch"]
    id: str
    latched: Literal["true", "false"]
    evidence: str = ""


class Pace(Command):
    op: Literal["pace"]
    nodule: dict[str, str]
    tasks: list[dict[str, str]] = Field(default_factory=list)
    requirements: list[dict[str, str]] = Field(default_factory=list)
    decisions: list[dict[str, str]] = Field(default_factory=list)


class Absorb(Command):
    op: Literal["absorb"]
    id: str


Operation = Annotated[
    Add | Set | Link | Move | Status | Latch | Pace | Absorb, Field(discriminator="op")
]
