from __future__ import annotations

import re
from typing import List, Tuple

from .models import Target

USERNAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")
TME = re.compile(r"^(?:https?://)?(?:www\.)?(?:t|telegram)\.me/(?P<path>[^?#\s]+)", re.I)
CHAT_ID = re.compile(r"^-\d{5,}$")
DIGITS = re.compile(r"^\d+$")


def normalize(raw: str) -> Tuple[str, str]:
    text = raw.strip()
    match = TME.match(text)
    if match:
        path = match.group("path").strip("/")
        if path.startswith("+") or path.lower().startswith("joinchat"):
            return "", "private invite links are not supported (tgcast never joins chats); use the @username or the chat id"
        text = path.split("/")[0]
    if text.startswith("@"):
        text = text[1:]
    if CHAT_ID.match(text):
        return text, ""
    if DIGITS.match(text):
        return "", "a positive number is a user id; direct messages are not supported"
    if USERNAME.match(text):
        return "@" + text, ""
    return "", f"'{raw.strip()}' is not a channel/group username, t.me link or chat id"


def parse_targets(text: str) -> Tuple[List[Target], List[str]]:
    targets: List[Target] = []
    errors: List[str] = []
    seen = set()
    for number, line in enumerate(text.splitlines(), 1):
        content = re.split(r"(?:^|\s)#", line, maxsplit=1)[0].strip()
        if not content:
            continue
        ref, problem = normalize(content.split()[0])
        if problem:
            errors.append(f"line {number}: {problem}")
            continue
        key = ref.lower()
        if key in seen:
            continue
        seen.add(key)
        targets.append(Target(ref=ref, line=number))
    return targets, errors
