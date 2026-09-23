from __future__ import annotations

import argparse
import csv
import getpass
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

from . import __version__
from .config import Config, load_config
from .errors import ConfigError, GatewayError
from .gateway import Gateway, TelethonGateway
from .models import FAILED, NOT_SENT, SENT, SKIPPED, Summary
from .sender import PlanItem, build_plan, context_for, send_all
from .store import History
from .targets import parse_targets
from .template import CONFIG_TEMPLATE, ENV_TEMPLATE, GITIGNORE_TEMPLATE, MESSAGE_TEMPLATE, TARGETS_TEMPLATE
from .templates import render, validate

GatewayFactory = Callable[[int, str, Path], Gateway]


@dataclass
class Runtime:
    factory: GatewayFactory = TelethonGateway
    say: Callable[[str], None] = field(default=lambda text="": print(text, flush=True))
    ask: Callable[[str, bool], str] = field(default=lambda prompt, secret: getpass.getpass(prompt) if secret else input(prompt))
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.time
    uniform: Callable[[float, float], float] = random.uniform

    def confirm(self, prompt: str) -> bool:
        return self.ask(f"{prompt} [y/N] ", False).strip().lower() in ("y", "yes")


DEFAULT_CONFIG = Path("tgcast.toml")


def find_config(explicit: Optional[str]) -> Path:
    path = Path(explicit) if explicit else DEFAULT_CONFIG
    if path.is_file():
        return path
    if explicit:
        raise ConfigError(f"config file not found: {explicit}")
    raise ConfigError("no tgcast.toml here. Run `tgcast setup` (guided), or use -c PATH")


def read_inputs(cfg: Config):
    if not cfg.message.file.is_file():
        raise ConfigError(f"message file not found: {cfg.message.file}")
    template = cfg.message.file.read_text(encoding="utf-8")
    problems = validate(template)
    if problems:
        raise ConfigError("\n".join(f"  - {p}" for p in problems))
    if cfg.message.attachment is not None and not cfg.message.attachment.is_file():
        raise ConfigError(f"attachment not found: {cfg.message.attachment}")
    if not cfg.targets_file.is_file():
        raise ConfigError(f"targets file not found: {cfg.targets_file}")
    targets, errors = parse_targets(cfg.targets_file.read_text(encoding="utf-8"))
    if errors:
        raise ConfigError("\n".join(f"  - {cfg.targets_file.name}: {e}" for e in errors))
    if not targets:
        raise ConfigError(f"{cfg.targets_file.name} has no chats yet; add one @username, t.me link or chat id per line")
    return template, targets


def open_gateway(cfg: Config, rt: Runtime) -> Gateway:
    gateway = rt.factory(cfg.telegram.api_id, cfg.telegram.api_hash, cfg.telegram.session)
    gateway.connect()
    if not gateway.is_authorized():
        gateway.close()
        raise ConfigError("you are not logged in yet. Run `tgcast setup` first.")
    return gateway


def describe(item: PlanItem) -> str:
    if item.action == "send":
        kind = item.resolved.kind if item.resolved else ""
        slow = ", slow mode" if item.resolved and item.resolved.slowmode else ""
        return f"  SEND  {item.title}  ({kind}{slow})"
    return f"  skip  {item.target.ref}  {item.title if item.resolved else ''} - {item.reason}".replace("  -", " -", 1)


def show_plan(plan: List[PlanItem], template: str, cfg: Config, rt: Runtime) -> int:
    sends = [i for i in plan if i.action == "send"]
    for item in plan:
        rt.say(describe(item))
    if sends and sends[0].resolved is not None:
        rt.say("")
        rt.say(f"Message preview (as sent to {sends[0].title}):")
        rt.say("  " + render(template, context_for(sends[0].resolved, rt.clock())).replace("\n", "\n  "))
        limits = cfg.limits
        average = (limits.delay_min + limits.delay_max) / 2
        pauses = 0
        if limits.batch_size:
            pauses = ((len(sends) - 1) // limits.batch_size) * limits.batch_pause
        minutes = max(0, ((len(sends) - 1) * average + pauses)) / 60
        rt.say("")
        rt.say(f"{len(sends)} chat(s) will get the message, about {minutes:.0f} min in total.")
    return len(sends)


def wait_until(moment: datetime, rt: Runtime) -> None:
    target = moment.timestamp()
    remaining = target - rt.clock()
    if remaining <= 0:
        return
    rt.say(f"Waiting until {moment:%Y-%m-%d %H:%M} ({remaining / 60:.0f} min). Keep this window open; Ctrl+C cancels.")
    while True:
        remaining = target - rt.clock()
        if remaining <= 0:
            return
        rt.sleep(min(30.0, remaining))


def write_report(cfg: Config, summary: Summary, rt: Runtime) -> None:
    if cfg.report.csv is None:
        return
    path = cfg.report.csv
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    stamp = datetime.fromtimestamp(rt.clock()).strftime("%Y-%m-%d %H:%M:%S")
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        if is_new:
            writer.writerow(["time", "target", "title", "status", "detail", "message_id"])
        for r in summary.results:
            writer.writerow([stamp, r.ref, r.title, r.status, r.detail, r.message_id or ""])


def summary_text(summary: Summary) -> str:
    text = (f"tgcast: sent {summary.count(SENT)}, skipped {summary.count(SKIPPED)}, "
            f"failed {summary.count(FAILED)}, not attempted {summary.count(NOT_SENT)}")
    if summary.stopped:
        text += f". Stopped: {summary.stopped}"
    return text


def cmd_send(args: argparse.Namespace, rt: Runtime) -> int:
    cfg = load_config(find_config(args.config))
    template, targets = read_inputs(cfg)
    when: Optional[datetime] = None
    if args.at:
        try:
            when = datetime.strptime(args.at, "%Y-%m-%d %H:%M")
        except ValueError as exc:
            raise ConfigError('--at expects "YYYY-MM-DD HH:MM" in local time, e.g. "2026-10-01 10:00"') from exc
        if when.timestamp() <= rt.clock() and not args.dry_run:
            raise ConfigError("--at is in the past")
    gateway = open_gateway(cfg, rt)
    history = History.load(cfg.history_file)
    try:
        if when is not None and not args.dry_run:
            wait_until(when, rt)
        plan = build_plan(targets, gateway, history, cfg, rt.clock(), rt.sleep, force=args.force,
                          limit=args.limit, log=rt.say)
        count = show_plan(plan, template, cfg, rt)
        if args.dry_run:
            rt.say("Dry run: nothing was sent.")
            return 0
        if count == 0:
            rt.say("Nothing to send.")
            return 0
        if not args.yes and not rt.confirm(f"Send to {count} chat(s) now?"):
            rt.say("Cancelled. Nothing was sent.")
            return 1
        summary = send_all(plan, template, cfg, gateway, history, rt.sleep, rt.clock, rt.uniform, rt.say)
        history.add_run({
            "time": rt.clock(), "sent": summary.count(SENT), "skipped": summary.count(SKIPPED),
            "failed": summary.count(FAILED), "not_sent": summary.count(NOT_SENT), "stopped": summary.stopped,
        })
        write_report(cfg, summary, rt)
        rt.say("")
        rt.say(summary_text(summary))
        if cfg.report.notify_self:
            try:
                gateway.send_to_self(summary_text(summary))
            except GatewayError as exc:
                rt.say(f"could not send the summary to Saved Messages: {exc}")
        if summary.stopped:
            return 3
        return 2 if summary.count(FAILED) else 0
    finally:
        gateway.close()


def cmd_check(args: argparse.Namespace, rt: Runtime) -> int:
    cfg = load_config(find_config(args.config))
    template, targets = read_inputs(cfg)
    rt.say(f"tgcast {__version__}  config: {cfg.path}")
    rt.say(f"message: {cfg.message.file.name} ({len(template)} characters), {len(targets)} chat(s) listed")
    gateway = open_gateway(cfg, rt)
    try:
        history = History.load(cfg.history_file)
        plan = build_plan(targets, gateway, history, cfg, rt.clock(), rt.sleep, force=True, limit=10_000, log=rt.say)
        for item in plan:
            rt.say(describe(item).replace("SEND ", "OK   "))
        problems = sum(1 for item in plan if item.action != "send")
        rt.say("")
        rt.say(f"{len(plan) - problems} chat(s) ready, {problems} with problems.")
        return 2 if problems else 0
    finally:
        gateway.close()


def cmd_status(args: argparse.Namespace, rt: Runtime) -> int:
    cfg = load_config(find_config(args.config))
    history = History.load(cfg.history_file)
    if not history.runs:
        rt.say("No runs yet.")
        return 0
    rt.say("Last runs:")
    for run in history.runs[-10:]:
        stamp = datetime.fromtimestamp(run["time"]).strftime("%Y-%m-%d %H:%M")
        line = f"  {stamp}  sent {run['sent']}, skipped {run['skipped']}, failed {run['failed']}"
        if run.get("stopped"):
            line += f"  (stopped: {run['stopped']})"
        rt.say(line)
    rt.say(f"{len(history.sent)} chat(s) have received the message at least once.")
    return 0


def cmd_setup(args: argparse.Namespace, rt: Runtime) -> int:
    directory = Path(args.dir) if args.dir else Path.cwd()
    directory.mkdir(parents=True, exist_ok=True)
    config_path = directory / "tgcast.toml"
    if config_path.exists() and not args.force:
        rt.say(f"{config_path} already exists. Use --force to overwrite the config (message and targets are kept).")
        return 1
    rt.say("tgcast setup")
    rt.say("You need an api_id and api_hash from https://my.telegram.org -> API development tools (a one-time step).")
    api_id = args.api_id or rt.ask("api_id: ", False).strip()
    api_hash = args.api_hash or rt.ask("api_hash: ", True).strip()
    if not api_id.isdigit() or not api_hash:
        rt.say("api_id must be a number and api_hash must not be empty.")
        return 1
    phone = args.phone or rt.ask("Your phone number in international format (+...): ", False).strip()
    session = directory / "tgcast.session"
    gateway = rt.factory(int(api_id), api_hash, session)
    try:
        gateway.connect()
        if gateway.is_authorized():
            rt.say("Already logged in.")
        else:
            name = gateway.login(
                phone, lambda: rt.ask("Code Telegram sent you: ", False).strip(),
                lambda: rt.ask("Two-step verification password: ", True))
            rt.say(f"Logged in as {name}.")
    except GatewayError as exc:
        rt.say(f"Login failed: {exc}")
        return 1
    finally:
        gateway.close()
    (directory / ".env").write_text(ENV_TEMPLATE.format(api_id=api_id, api_hash=api_hash), encoding="utf-8")
    try:
        (directory / ".env").chmod(0o600)
    except OSError:
        pass
    config_path.write_text(CONFIG_TEMPLATE, encoding="utf-8")
    for name, content in (("message.md", MESSAGE_TEMPLATE), ("targets.txt", TARGETS_TEMPLATE),
                          (".gitignore", GITIGNORE_TEMPLATE)):
        path = directory / name
        if not path.exists():
            path.write_text(content, encoding="utf-8")
    rt.say("")
    rt.say(f"Done. Files are in {directory}")
    rt.say("Next: put your text in message.md, your chats in targets.txt, then run")
    rt.say("  tgcast check         to see which chats you can post to")
    rt.say("  tgcast send --dry-run   to preview, and tgcast send to send")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tgcast",
        description="Careful announcements to your own Telegram channels and groups.",
    )
    parser.add_argument("--version", action="version", version=f"tgcast {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p = sub.add_parser("setup", help="guided setup: log in and create the config, message and targets files")
    p.add_argument("--dir", help="where to create the files (default: the current folder)")
    p.add_argument("--api-id")
    p.add_argument("--api-hash")
    p.add_argument("--phone")
    p.add_argument("--force", action="store_true", help="overwrite tgcast.toml")

    for name, help_text in (("check", "check the config and which chats you can post to"),
                            ("send", "send the message"), ("status", "show what was sent before")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("-c", "--config", help="path to tgcast.toml (default: ./tgcast.toml)")
        if name == "send":
            p.add_argument("--dry-run", action="store_true", help="show the plan and a preview, send nothing")
            p.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation")
            p.add_argument("--force", action="store_true", help="ignore the cooldown for chats already written to")
            p.add_argument("--limit", type=int, help="send to at most this many chats in this run")
            p.add_argument("--at", metavar="'YYYY-MM-DD HH:MM'", help="wait until this local time, then send")
    return parser


def main(argv: Optional[List[str]] = None, runtime: Optional[Runtime] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    rt = runtime or Runtime()
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {"setup": cmd_setup, "check": cmd_check, "send": cmd_send, "status": cmd_status}
    handler = handlers.get(args.command or "")
    if handler is None:
        parser.print_help()
        return 0
    try:
        return int(handler(args, rt))
    except ConfigError as exc:
        print(f"Problem:\n{exc}", file=sys.stderr)
        return 1
    except GatewayError as exc:
        print(f"Telegram problem: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
