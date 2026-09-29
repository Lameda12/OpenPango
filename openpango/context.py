"""Execution context shared by agents. Ctx.tool() is the only way an agent touches state."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field, replace
from datetime import datetime

from . import policy
from .drafters import Drafter, TemplateDrafter
from .mocks.carrier import MockCarrier


@dataclass
class Ctx:
    conn: sqlite3.Connection
    now: datetime
    actor: str = "system"
    drafter: Drafter = field(default_factory=TemplateDrafter)
    carrier: MockCarrier = field(default_factory=MockCarrier)
    trace: list = field(default_factory=list)   # shared across as_actor copies

    def as_actor(self, actor: str) -> "Ctx":
        return replace(self, actor=actor)

    def tool(self, name: str, **kwargs):
        from . import tools
        if name not in policy.AGENT_TOOLS.get(self.actor, frozenset()):
            raise PermissionError(f"{self.actor} may not call {name}")
        result = tools.REGISTRY[name](self, **kwargs)
        self.trace.append({"actor": self.actor, "tool": name, "args": kwargs, "event_id": result.get("event_id")})
        return result
