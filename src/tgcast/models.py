from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

SENT = "sent"
SKIPPED = "skipped"
FAILED = "failed"
NOT_SENT = "not_sent"


@dataclass(frozen=True)
class Target:
    ref: str
    line: int = 0


@dataclass
class Resolved:
    target: Target
    id: int
    title: str
    username: Optional[str]
    kind: str
    can_post: bool
    reason: str = ""
    slowmode: bool = False


@dataclass
class Result:
    ref: str
    title: str
    status: str
    detail: str = ""
    message_id: Optional[int] = None


@dataclass
class Summary:
    results: List[Result] = field(default_factory=list)
    stopped: str = ""

    def count(self, status: str) -> int:
        return sum(1 for r in self.results if r.status == status)
