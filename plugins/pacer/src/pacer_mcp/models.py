"""Typed command schemas published through MCP tool input schemas."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class Command(BaseModel):
    """Disallow misspelled operation fields at the transport boundary."""

    model_config = ConfigDict(extra="forbid")


class Add(Command):
    op: Literal["add"]
    register_name: Literal["todo", "overlord"] = Field(alias="register")
    row: dict[str, str]


class Set(Command):
    op: Literal["set"]
    id: str
    fields: dict[str, str]


class Append(Command):
    op: Literal["append"]
    id: str
    field: Literal["Notes", "LearningNotes", "PreviousAttempts"]
    text: str


class Link(Command):
    op: Literal["link"]
    id: str
    field: str
    target: str
    remove: bool = False


class Transition(Command):
    op: Literal["transition"]
    id: str
    status: Literal[
        "TODO", "DOING", "REVIEW", "DONE", "SCAFFOLD", "PACED_REQUIREMENT", "VALIDATED_COMPLETE"
    ]
    evidence: str = ""


class Pace(Command):
    op: Literal["pace"]
    nodule: dict[str, str]
    tasks: list[dict[str, str]]
    requirements: list[dict[str, str]] = Field(default_factory=list)


class Split(Command):
    op: Literal["split"]
    id: str
    children: list[dict[str, str]]


class Absorb(Command):
    op: Literal["absorb"]
    id: str
    evidence: str


class ContextReceipt(Command):
    task: str
    root: str
    basis: str = Field(pattern=r"^[a-f0-9]{64}$")


class Verify(Command):
    op: Literal["verify"]
    id: str
    evidence: str
    artifact: str = ""


class Checkpoint(Command):
    op: Literal["checkpoint"]
    id: str
    next_action: Literal["inspect", "implement", "verify", "review", "absorb", "resolve"]


class Refresh(Command):
    op: Literal["refresh"]
    id: str


Operation = Annotated[
    Add | Set | Append | Link | Transition | Pace | Split | Absorb | Verify | Checkpoint | Refresh,
    Field(discriminator="op"),
]
