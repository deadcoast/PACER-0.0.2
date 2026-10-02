"""Typed operations for the MCP tool schema."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class Command(BaseModel):
    """Reject misspelled operation fields at the transport boundary."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


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


class Archive(Command):
    op: Literal["archive"]
    ids: list[str] = Field(min_length=1)
    cascade: bool = True


class Repath(Command):
    op: Literal["repath"]
    source: str = Field(alias="from")
    target: str = Field(alias="to")


Operation = Annotated[
    Add | Set | Link | Move | Status | Latch | Pace | Absorb | Archive | Repath,
    Field(discriminator="op"),
]
