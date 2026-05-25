from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class RegisteredAgent(Protocol):
    name: str


@dataclass(frozen=True)
class AgentDescriptor:
    name: str
    kind: str
    agent: RegisteredAgent | Any
    description: str = ""


class AgentRegistry:
    """Expandable registry for CharacterAgent and SpecialistAgent instances."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentDescriptor] = {}

    def register(self, name: str, agent: RegisteredAgent | Any, *, kind: str, description: str = "") -> None:
        self._agents[name] = AgentDescriptor(name=name, kind=kind, agent=agent, description=description)

    def get(self, name: str) -> AgentDescriptor:
        return self._agents[name]

    def list(self) -> list[AgentDescriptor]:
        return list(self._agents.values())

