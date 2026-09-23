from __future__ import annotations

import string
from typing import Dict, List

ALLOWED = ("title", "username", "id", "date")


def placeholders(template: str) -> List[str]:
    names: List[str] = []
    try:
        for _, field, _, _ in string.Formatter().parse(template):
            if field is not None:
                names.append(field.split(".")[0].split("[")[0])
    except ValueError as exc:
        raise ValueError(f"the message has a broken {{placeholder}}: {exc}") from exc
    return names


def validate(template: str) -> List[str]:
    problems: List[str] = []
    if not template.strip():
        problems.append("the message is empty")
        return problems
    try:
        names = placeholders(template)
    except ValueError as exc:
        return [str(exc)]
    for name in sorted(set(names)):
        if name not in ALLOWED:
            problems.append(f"unknown placeholder {{{name}}}; available: " + ", ".join("{" + a + "}" for a in ALLOWED))
    return problems


def render(template: str, context: Dict[str, str]) -> str:
    values = {name: context.get(name, "") for name in ALLOWED}
    return template.format(**values).strip()
