from __future__ import annotations

import difflib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

from .errors import ConfigError

ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
PARSE_MODES = ("markdown", "html", "none")
MAX_PER_RUN_CEILING = 500


@dataclass
class TelegramCfg:
    api_id: int
    api_hash: str
    session: Path


@dataclass
class MessageCfg:
    file: Path
    parse_mode: Optional[str] = "markdown"
    attachment: Optional[Path] = None
    link_preview: bool = False


@dataclass
class LimitsCfg:
    delay_min: int = 20
    delay_max: int = 60
    batch_size: int = 10
    batch_pause: int = 300
    max_per_run: int = 20
    cooldown_hours: int = 24
    flood_wait_max: int = 300
    retries: int = 2


@dataclass
class ReportCfg:
    csv: Optional[Path] = None
    notify_self: bool = False


@dataclass
class Config:
    telegram: TelegramCfg
    message: MessageCfg
    targets_file: Path
    history_file: Path
    limits: LimitsCfg = field(default_factory=LimitsCfg)
    report: ReportCfg = field(default_factory=ReportCfg)
    base: Path = Path(".")
    path: Optional[Path] = None


def parse_env_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


class Problems:
    def __init__(self) -> None:
        self.items: List[str] = []

    def add(self, where: str, message: str) -> None:
        self.items.append(f"{where}: {message}")


def interpolate(value: Any, env: Dict[str, str], where: str, problems: Problems) -> Any:
    if isinstance(value, str):

        def replace(match: re.Match[str]) -> str:
            name, default = match.group(1), match.group(2)
            if env.get(name):
                return env[name]
            if default is not None:
                return default
            problems.add(where, f"environment variable {name} is not set (put it in the .env file next to the config)")
            return ""

        return ENV_RE.sub(replace, value)
    if isinstance(value, dict):
        return {k: interpolate(v, env, f"{where}.{k}" if where else k, problems) for k, v in value.items()}
    if isinstance(value, list):
        return [interpolate(v, env, f"{where}[{i}]", problems) for i, v in enumerate(value)]
    return value


def check_keys(table: Dict[str, Any], where: str, allowed: List[str], problems: Problems) -> None:
    for key in table:
        if key not in allowed:
            hint = difflib.get_close_matches(key, allowed, n=1)
            more = f" (did you mean '{hint[0]}'?)" if hint else f" (allowed: {', '.join(allowed)})"
            problems.add(f"{where}.{key}" if where else key, f"unknown setting{more}")


def section(data: Dict[str, Any], name: str, problems: Problems) -> Dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        problems.add(name, f"must be a table, e.g. [{name}]")
        return {}
    return value


def integer(table: Dict[str, Any], where: str, key: str, default: int, problems: Problems, minimum: int = 0) -> int:
    if key not in table:
        return default
    value = table[key]
    if isinstance(value, bool) or not isinstance(value, int):
        problems.add(f"{where}.{key}", "must be a whole number")
        return default
    if value < minimum:
        problems.add(f"{where}.{key}", f"must be >= {minimum}")
        return default
    return value


def string(table: Dict[str, Any], where: str, key: str, default: str, problems: Problems) -> str:
    if key not in table:
        return default
    value = table[key]
    if not isinstance(value, str):
        problems.add(f"{where}.{key}", "must be text in quotes")
        return default
    return value


def boolean(table: Dict[str, Any], where: str, key: str, default: bool, problems: Problems) -> bool:
    if key not in table:
        return default
    value = table[key]
    if not isinstance(value, bool):
        problems.add(f"{where}.{key}", "must be true or false")
        return default
    return value


def resolve_path(base: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base / path


def parse_config(data: Dict[str, Any], env: Dict[str, str], base: Path) -> Config:
    problems = Problems()
    data = interpolate(data, env, "", problems)
    check_keys(data, "", ["telegram", "message", "targets", "limits", "report", "history"], problems)

    tg = section(data, "telegram", problems)
    check_keys(tg, "telegram", ["api_id", "api_hash", "session"], problems)
    raw_id = tg.get("api_id", "")
    try:
        api_id = int(str(raw_id).strip())
    except ValueError:
        api_id = 0
        problems.add("telegram.api_id", "must be a number (get it at https://my.telegram.org -> API development tools)")
    api_hash = string(tg, "telegram", "api_hash", "", problems).strip()
    if not api_hash:
        problems.add("telegram.api_hash", "is required (https://my.telegram.org -> API development tools)")
    session = resolve_path(base, string(tg, "telegram", "session", "tgcast.session", problems))

    msg = section(data, "message", problems)
    check_keys(msg, "message", ["file", "parse_mode", "attachment", "link_preview"], problems)
    mode = string(msg, "message", "parse_mode", "markdown", problems)
    if mode not in PARSE_MODES:
        problems.add("message.parse_mode", f"must be one of: {', '.join(PARSE_MODES)}")
        mode = "markdown"
    attachment = string(msg, "message", "attachment", "", problems)
    message = MessageCfg(
        file=resolve_path(base, string(msg, "message", "file", "message.md", problems)),
        parse_mode=None if mode == "none" else mode,
        attachment=resolve_path(base, attachment) if attachment else None,
        link_preview=boolean(msg, "message", "link_preview", False, problems),
    )

    tgt = section(data, "targets", problems)
    check_keys(tgt, "targets", ["file"], problems)
    targets_file = resolve_path(base, string(tgt, "targets", "file", "targets.txt", problems))

    lim = section(data, "limits", problems)
    check_keys(
        lim, "limits",
        ["delay_min", "delay_max", "batch_size", "batch_pause", "max_per_run", "cooldown_hours", "flood_wait_max", "retries"],
        problems,
    )
    limits = LimitsCfg(
        delay_min=integer(lim, "limits", "delay_min", 20, problems, 1),
        delay_max=integer(lim, "limits", "delay_max", 60, problems, 1),
        batch_size=integer(lim, "limits", "batch_size", 10, problems, 0),
        batch_pause=integer(lim, "limits", "batch_pause", 300, problems, 0),
        max_per_run=integer(lim, "limits", "max_per_run", 20, problems, 1),
        cooldown_hours=integer(lim, "limits", "cooldown_hours", 24, problems, 0),
        flood_wait_max=integer(lim, "limits", "flood_wait_max", 300, problems, 0),
        retries=integer(lim, "limits", "retries", 2, problems, 0),
    )
    if limits.delay_min > limits.delay_max:
        problems.add("limits.delay_min", "must not be greater than delay_max")
    if limits.max_per_run > MAX_PER_RUN_CEILING:
        problems.add("limits.max_per_run", f"must be <= {MAX_PER_RUN_CEILING}; split a big list over several runs")

    rep = section(data, "report", problems)
    check_keys(rep, "report", ["csv", "notify_self"], problems)
    csv_name = string(rep, "report", "csv", "", problems)
    report = ReportCfg(
        csv=resolve_path(base, csv_name) if csv_name else None,
        notify_self=boolean(rep, "report", "notify_self", False, problems),
    )

    hist = section(data, "history", problems)
    check_keys(hist, "history", ["file"], problems)
    history_file = resolve_path(base, string(hist, "history", "file", "history.json", problems))

    if problems.items:
        raise ConfigError("\n".join(f"  - {item}" for item in problems.items))
    return Config(
        telegram=TelegramCfg(api_id=api_id, api_hash=api_hash, session=session),
        message=message,
        targets_file=targets_file,
        history_file=history_file,
        limits=limits,
        report=report,
        base=base,
    )


def load_config(path: Path, env: Optional[Dict[str, str]] = None) -> Config:
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}  (create one with `tgcast setup`)")
    merged: Dict[str, str] = {}
    env_file = path.parent / ".env"
    if env_file.is_file():
        merged.update(parse_env_file(env_file))
    merged.update(os.environ if env is None else env)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path.name} is not valid TOML: {exc}") from exc
    cfg = parse_config(data, merged, path.parent.resolve())
    cfg.path = path.resolve()
    return cfg
