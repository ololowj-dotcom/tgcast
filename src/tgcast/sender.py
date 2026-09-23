from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from .config import Config
from .errors import Fatal, FloodWait, GatewayError, NotFound, Restricted, Transient
from .gateway import Gateway
from .models import FAILED, NOT_SENT, SENT, SKIPPED, Resolved, Result, Summary, Target
from .store import History
from .templates import render

Log = Callable[[str], None]
Sleep = Callable[[float], None]
Uniform = Callable[[float, float], float]

RESOLVE_PAUSE = 1.0


@dataclass
class PlanItem:
    target: Target
    resolved: Optional[Resolved]
    action: str
    reason: str = ""

    @property
    def title(self) -> str:
        return self.resolved.title if self.resolved else self.target.ref


@dataclass
class Attempt:
    ok: bool
    message_id: Optional[int] = None
    detail: str = ""
    stop: bool = False


def build_plan(
    targets: List[Target],
    gateway: Gateway,
    history: History,
    cfg: Config,
    now: float,
    sleep: Sleep,
    force: bool = False,
    limit: Optional[int] = None,
    log: Log = lambda _msg: None,
) -> List[PlanItem]:
    plan: List[PlanItem] = []
    cooldown = cfg.limits.cooldown_hours * 3600
    cap = min(limit, cfg.limits.max_per_run) if limit else cfg.limits.max_per_run
    ready = 0
    for index, target in enumerate(targets):
        if index:
            sleep(RESOLVE_PAUSE)
        try:
            resolved = gateway.resolve(target)
        except FloodWait as exc:
            log(f"Telegram asked to wait {exc.seconds}s while looking up chats; the lookup stops here")
            for rest in targets[index:]:
                plan.append(PlanItem(rest, None, "skip", "lookup rate-limited; run again a little later"))
            break
        except (Restricted, Fatal):
            raise
        except NotFound as exc:
            plan.append(PlanItem(target, None, "skip", str(exc)))
            continue
        except GatewayError as exc:
            plan.append(PlanItem(target, None, "skip", str(exc)))
            continue
        if not resolved.can_post:
            plan.append(PlanItem(target, resolved, "skip", resolved.reason))
            continue
        last = history.last_sent(resolved.id)
        if last is not None and not force and now - last < cooldown:
            hours = (now - last) / 3600
            reason = f"already sent {hours:.1f}h ago (cooldown {cfg.limits.cooldown_hours}h; --force overrides)"
            plan.append(PlanItem(target, resolved, "skip", reason))
            continue
        if ready >= cap:
            plan.append(PlanItem(target, resolved, "skip", f"over the limit of {cap} per run; it goes in the next run"))
            continue
        ready += 1
        plan.append(PlanItem(target, resolved, "send"))
    return plan


def context_for(resolved: Resolved, now: float) -> Dict[str, str]:
    return {
        "title": resolved.title,
        "username": resolved.username or "",
        "id": str(resolved.id),
        "date": time.strftime("%Y-%m-%d", time.localtime(now)),
    }


def attempt(resolved: Resolved, text: str, cfg: Config, gateway: Gateway, sleep: Sleep, log: Log) -> Attempt:
    tries = 0
    while True:
        try:
            message_id = gateway.send(
                resolved, text, cfg.message.attachment, cfg.message.parse_mode, cfg.message.link_preview)
            return Attempt(True, message_id)
        except FloodWait as exc:
            if exc.seconds > cfg.limits.flood_wait_max:
                detail = (
                    f"Telegram asks to wait {exc.seconds}s, more than flood_wait_max={cfg.limits.flood_wait_max}s; "
                    "the run was stopped, try again later"
                )
                return Attempt(False, detail=detail, stop=True)
            tries += 1
            if tries > cfg.limits.retries:
                return Attempt(False, detail=f"still rate-limited after {tries} waits")
            log(f"Telegram asks to wait {exc.seconds}s; waiting")
            sleep(exc.seconds + 2)
        except Transient as exc:
            tries += 1
            if tries > cfg.limits.retries:
                return Attempt(False, detail=str(exc))
            log(f"{exc}; retrying")
            sleep(5 * tries)
        except (Restricted, Fatal) as exc:
            return Attempt(False, detail=str(exc), stop=True)
        except GatewayError as exc:
            return Attempt(False, detail=str(exc))


def send_all(
    plan: List[PlanItem],
    template: str,
    cfg: Config,
    gateway: Gateway,
    history: History,
    sleep: Sleep,
    clock: Callable[[], float],
    uniform: Uniform,
    log: Log,
) -> Summary:
    summary = Summary()
    for item in plan:
        if item.action == "skip":
            summary.results.append(Result(item.target.ref, item.title, SKIPPED, item.reason))
    todo = [item for item in plan if item.action == "send" and item.resolved is not None]
    limits = cfg.limits
    sent_count = 0
    done = 0
    try:
        for position, item in enumerate(todo):
            resolved = item.resolved
            text = render(template, context_for(resolved, clock()))
            outcome = attempt(resolved, text, cfg, gateway, sleep, log)
            done = position + 1
            if outcome.ok:
                summary.results.append(Result(item.target.ref, resolved.title, SENT, "", outcome.message_id))
                history.record_sent(resolved.id, resolved.title, clock(), outcome.message_id)
                sent_count += 1
                log(f"sent    {resolved.title}")
                if position < len(todo) - 1:
                    if limits.batch_size and sent_count % limits.batch_size == 0:
                        log(f"batch of {limits.batch_size} done, pausing {limits.batch_pause}s")
                        sleep(limits.batch_pause)
                    else:
                        sleep(uniform(limits.delay_min, limits.delay_max))
                continue
            summary.results.append(Result(item.target.ref, resolved.title, FAILED, outcome.detail))
            log(f"failed  {resolved.title}: {outcome.detail}")
            if outcome.stop:
                summary.stopped = outcome.detail
                log(f"STOPPED: {outcome.detail}")
                break
    except KeyboardInterrupt:
        summary.stopped = "interrupted by the user"
        log("interrupted by the user")
    for item in todo[done:]:
        summary.results.append(Result(item.target.ref, item.title, NOT_SENT, summary.stopped or "not attempted"))
    return summary
