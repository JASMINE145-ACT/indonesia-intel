from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SocialHit:
    url: str
    title: str = ""
    snippet: str = ""
    query: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class SocialSearchOutcome:
    ok: bool
    reason: str | None = None
    provider: str = ""
    discovery_method: str = ""
    hits: list[SocialHit] = field(default_factory=list)
