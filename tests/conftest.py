from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pytest

from tgcast.cli import Runtime
from tgcast.config import Config, parse_config
from tgcast.errors import GatewayError, NotFound
from tgcast.models import Resolved, Target

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


def make_resolved(ref: str, id: int = 0, title: str = "", kind: str = "supergroup", can_post: bool = True,
                  reason: str = "", slowmode: bool = False) -> Resolved:
    number = id or abs(hash(ref)) % 10_000_000
    return Resolved(target=Target(ref), id=number, title=title or ref.lstrip("@"), username=ref.lstrip("@"),
                    kind=kind, can_post=can_post, reason=reason, slowmode=slowmode)


class FakeGateway:
    def __init__(self) -> None:
        self.resolved: Dict[str, Any] = {}
        self.send_plan: Dict[str, List[Any]] = {}
        self.sent: List[Dict[str, Any]] = []
        self.self_messages: List[str] = []
        self.authorized = True
        self.login_calls: List[str] = []
        self.login_error: Optional[GatewayError] = None
        self.needs_password = False
        self.closed = False
        self.resolve_calls: List[str] = []

    def add(self, ref: str, **kw: Any) -> Resolved:
        item = make_resolved(ref, **kw)
        self.resolved[ref] = item
        return item

    def connect(self) -> None:
        pass

    def is_authorized(self) -> bool:
        return self.authorized

    def login(self, phone: str, ask_code: Callable[[], str], ask_password: Callable[[], str]) -> str:
        if self.login_error:
            raise self.login_error
        code = ask_code()
        self.login_calls.append(f"{phone}:{code}")
        if self.needs_password:
            self.login_calls.append("password:" + ask_password())
        self.authorized = True
        return "@tester"

    def resolve(self, target: Target) -> Resolved:
        self.resolve_calls.append(target.ref)
        item = self.resolved.get(target.ref)
        if item is None:
            raise NotFound("no such chat or username")
        if isinstance(item, Exception):
            raise item
        return item

    def send(self, resolved: Resolved, text: str, attachment: Optional[Path], parse_mode: Optional[str],
             link_preview: bool) -> Optional[int]:
        script = self.send_plan.get(resolved.target.ref)
        if script:
            step = script.pop(0)
            if isinstance(step, Exception):
                raise step
        self.sent.append({"ref": resolved.target.ref, "title": resolved.title, "text": text,
                          "attachment": attachment, "parse_mode": parse_mode, "preview": link_preview})
        return 1000 + len(self.sent)

    def send_to_self(self, text: str) -> None:
        self.self_messages.append(text)

    def close(self) -> None:
        self.closed = True


class Recorder:
    def __init__(self, start: float = 1_800_000_000.0) -> None:
        self.now = start
        self.sleeps: List[float] = []
        self.said: List[str] = []
        self.answers: List[str] = []
        self.asked: List[str] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def clock(self) -> float:
        return self.now

    def say(self, text: str = "") -> None:
        self.said.append(text)

    def ask(self, prompt: str, secret: bool) -> str:
        self.asked.append(prompt)
        return self.answers.pop(0) if self.answers else ""

    @property
    def text(self) -> str:
        return "\n".join(self.said)


def runtime(gateway: FakeGateway, rec: Recorder) -> Runtime:
    return Runtime(
        factory=lambda api_id, api_hash, session: gateway,
        say=rec.say, ask=rec.ask, sleep=rec.sleep, clock=rec.clock, uniform=lambda low, high: (low + high) / 2,
    )


def make_cfg(toml_text: str = "", base: Optional[Path] = None) -> Config:
    body = '[telegram]\napi_id = "12345"\napi_hash = "abcdef"\n' + toml_text
    return parse_config(tomllib.loads(body), {}, Path(base) if base else Path.cwd())


@pytest.fixture
def gateway() -> FakeGateway:
    return FakeGateway()


@pytest.fixture
def rec() -> Recorder:
    return Recorder()


@pytest.fixture
def project(tmp_path):
    (tmp_path / "message.md").write_text("Hello {title} on {date}", encoding="utf-8")
    (tmp_path / "targets.txt").write_text("@alpha_chat\n@beta_chat\n@gamma_chat\n", encoding="utf-8")
    (tmp_path / "tgcast.toml").write_text(
        '[telegram]\napi_id = "12345"\napi_hash = "abcdef"\n'
        '[limits]\ndelay_min = 10\ndelay_max = 20\nbatch_size = 0\nmax_per_run = 20\ncooldown_hours = 24\n',
        encoding="utf-8")
    return tmp_path
