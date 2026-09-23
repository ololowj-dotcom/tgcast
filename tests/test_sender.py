from conftest import make_cfg

from tgcast.errors import Fatal, FloodWait, Forbidden, NotFound, Restricted, Transient
from tgcast.models import FAILED, NOT_SENT, SENT, SKIPPED, Target
from tgcast.sender import build_plan, send_all
from tgcast.store import History


def setup(gateway, refs, toml=""):
    cfg = make_cfg("[limits]\ndelay_min = 10\ndelay_max = 20\nbatch_size = 0\n" + toml)
    for ref in refs:
        gateway.add(ref)
    return cfg, [Target(r) for r in refs]


def plan_for(gateway, targets, cfg, rec, history=None, **kw):
    return build_plan(targets, gateway, history or History(None), cfg, rec.now, rec.sleep, **kw)


def run(plan, cfg, gateway, rec, history=None, template="Hi {title}"):
    return send_all(plan, template, cfg, gateway, history or History(None), rec.sleep, rec.clock,
                    lambda low, high: (low + high) / 2, rec.say)


def statuses(summary):
    return [(r.ref, r.status) for r in summary.results]


def test_everything_ready_is_sent_with_pauses_between_but_not_after_the_last(gateway, rec):
    cfg, targets = setup(gateway, ["@aaa_chat", "@bbb_chat", "@ccc_chat"])
    summary = run(plan_for(gateway, targets, cfg, rec), cfg, gateway, rec)
    assert [r.status for r in summary.results] == [SENT] * 3
    assert [m["text"] for m in gateway.sent] == ["Hi aaa_chat", "Hi bbb_chat", "Hi ccc_chat"]
    pauses = [s for s in rec.sleeps if s == 15]
    assert len(pauses) == 2
    assert rec.sleeps[-1] != 15 or len(pauses) == 2


def test_pause_is_random_within_bounds(gateway, rec):
    cfg, targets = setup(gateway, ["@aaa_chat", "@bbb_chat"])
    plan = plan_for(gateway, targets, cfg, rec)
    send_all(plan, "x", cfg, gateway, History(None), rec.sleep, rec.clock, lambda low, high: high, rec.say)
    assert 20 in rec.sleeps


def test_batch_pause_replaces_the_normal_delay(gateway, rec):
    cfg, targets = setup(gateway, [f"@chat_{i}_x" for i in range(5)],
                         "")
    cfg.limits.batch_size, cfg.limits.batch_pause = 2, 300
    run(plan_for(gateway, targets, cfg, rec), cfg, gateway, rec)
    assert rec.sleeps.count(300) == 2
    assert len([s for s in rec.sleeps if s == 15]) == 2


def test_no_pause_after_the_final_message_even_at_a_batch_boundary(gateway, rec):
    cfg, targets = setup(gateway, ["@aaa_chat", "@bbb_chat"])
    cfg.limits.batch_size, cfg.limits.batch_pause = 2, 300
    run(plan_for(gateway, targets, cfg, rec), cfg, gateway, rec)
    assert 300 not in rec.sleeps


def test_max_per_run_caps_the_plan(gateway, rec):
    cfg, targets = setup(gateway, ["@aaa_chat", "@bbb_chat", "@ccc_chat"], "")
    cfg.limits.max_per_run = 2
    plan = plan_for(gateway, targets, cfg, rec)
    assert [i.action for i in plan] == ["send", "send", "skip"]
    assert "next run" in plan[2].reason


def test_limit_argument_can_only_lower_the_cap(gateway, rec):
    cfg, targets = setup(gateway, ["@aaa_chat", "@bbb_chat", "@ccc_chat"])
    assert [i.action for i in plan_for(gateway, targets, cfg, rec, limit=1)] == ["send", "skip", "skip"]
    cfg.limits.max_per_run = 1
    assert [i.action for i in plan_for(gateway, targets, cfg, rec, limit=50)] == ["send", "skip", "skip"]


def test_unresolvable_and_forbidden_chats_are_skipped_with_reasons(gateway, rec):
    cfg, targets = setup(gateway, ["@ok_chat"])
    gateway.add("@locked_chat", can_post=False, reason="you are restricted in this group")
    gateway.add("@person_chat", kind="user", can_post=False, reason="direct messages are not supported")
    targets += [Target("@locked_chat"), Target("@missing_chat"), Target("@person_chat")]
    plan = plan_for(gateway, targets, cfg, rec)
    assert [(i.action, i.reason) for i in plan] == [
        ("send", ""),
        ("skip", "you are restricted in this group"),
        ("skip", "no such chat or username"),
        ("skip", "direct messages are not supported"),
    ]


def test_cooldown_skips_recent_chats_unless_forced(gateway, rec):
    cfg, targets = setup(gateway, ["@aaa_chat", "@bbb_chat"])
    history = History(None)
    history.record_sent(gateway.resolved["@aaa_chat"].id, "aaa", rec.now - 3600, 1)
    plan = plan_for(gateway, targets, cfg, rec, history)
    assert [i.action for i in plan] == ["skip", "send"] and "already sent 1.0h ago" in plan[0].reason
    assert [i.action for i in plan_for(gateway, targets, cfg, rec, history, force=True)] == ["send", "send"]
    history.record_sent(gateway.resolved["@aaa_chat"].id, "aaa", rec.now - 25 * 3600, 1)
    assert [i.action for i in plan_for(gateway, targets, cfg, rec, history)] == ["send", "send"]


def test_cooldown_of_zero_disables_the_guard(gateway, rec):
    cfg, targets = setup(gateway, ["@aaa_chat"], "")
    cfg.limits.cooldown_hours = 0
    history = History(None)
    history.record_sent(gateway.resolved["@aaa_chat"].id, "a", rec.now - 1, 1)
    assert plan_for(gateway, targets, cfg, rec, history)[0].action == "send"


def test_sent_chats_are_recorded_so_a_second_run_skips_them(gateway, rec):
    cfg, targets = setup(gateway, ["@aaa_chat", "@bbb_chat"])
    history = History(None)
    run(plan_for(gateway, targets, cfg, rec, history), cfg, gateway, rec, history)
    second = plan_for(gateway, targets, cfg, rec, history)
    assert [i.action for i in second] == ["skip", "skip"]
    assert len(gateway.sent) == 2


def test_lookups_are_paced(gateway, rec):
    cfg, targets = setup(gateway, ["@aaa_chat", "@bbb_chat", "@ccc_chat"])
    plan_for(gateway, targets, cfg, rec)
    assert rec.sleeps == [1.0, 1.0]


def test_lookup_flood_wait_stops_the_lookup_but_keeps_the_rest_of_the_list(gateway, rec):
    cfg, targets = setup(gateway, ["@aaa_chat"])
    gateway.resolved["@bbb_chat"] = FloodWait(600)
    targets += [Target("@bbb_chat"), Target("@ccc_chat")]
    plan = plan_for(gateway, targets, cfg, rec)
    assert [i.action for i in plan] == ["send", "skip", "skip"] and "rate-limited" in plan[1].reason


def test_lookup_fatal_errors_propagate(gateway, rec):
    cfg, targets = setup(gateway, [])
    gateway.resolved["@aaa_chat"] = Fatal("session revoked")
    try:
        plan_for(gateway, [Target("@aaa_chat")], cfg, rec)
    except Fatal:
        return
    raise AssertionError("Fatal should propagate")


def test_lookup_other_errors_become_skips(gateway, rec):
    cfg, _ = setup(gateway, [])
    gateway.resolved["@aaa_chat"] = Transient("network problem")
    plan = plan_for(gateway, [Target("@aaa_chat")], cfg, rec)
    assert plan[0].action == "skip" and "network" in plan[0].reason


def test_forbidden_target_fails_only_itself(gateway, rec):
    cfg, targets = setup(gateway, ["@aaa_chat", "@bbb_chat", "@ccc_chat"])
    gateway.send_plan["@bbb_chat"] = [Forbidden("you are not allowed to write in this chat")]
    summary = run(plan_for(gateway, targets, cfg, rec), cfg, gateway, rec)
    assert statuses(summary) == [("@aaa_chat", SENT), ("@bbb_chat", FAILED), ("@ccc_chat", SENT)]
    assert not summary.stopped and "not allowed" in summary.results[1].detail


def test_short_flood_wait_is_waited_out_and_retried(gateway, rec):
    cfg, targets = setup(gateway, ["@aaa_chat"])
    gateway.send_plan["@aaa_chat"] = [FloodWait(30)]
    summary = run(plan_for(gateway, targets, cfg, rec), cfg, gateway, rec)
    assert summary.results[0].status == SENT and 32 in rec.sleeps


def test_repeated_flood_waits_give_up_on_that_chat_only(gateway, rec):
    cfg, targets = setup(gateway, ["@aaa_chat", "@bbb_chat"], "")
    cfg.limits.retries = 1
    gateway.send_plan["@aaa_chat"] = [FloodWait(5), FloodWait(5)]
    summary = run(plan_for(gateway, targets, cfg, rec), cfg, gateway, rec)
    assert statuses(summary) == [("@aaa_chat", FAILED), ("@bbb_chat", SENT)]


def test_long_flood_wait_stops_the_whole_run(gateway, rec):
    cfg, targets = setup(gateway, ["@aaa_chat", "@bbb_chat", "@ccc_chat"])
    gateway.send_plan["@bbb_chat"] = [FloodWait(3600)]
    summary = run(plan_for(gateway, targets, cfg, rec), cfg, gateway, rec)
    assert statuses(summary) == [("@aaa_chat", SENT), ("@bbb_chat", FAILED), ("@ccc_chat", NOT_SENT)]
    assert "3600s" in summary.stopped and 3602 not in rec.sleeps


def test_peer_flood_stops_immediately_with_advice(gateway, rec):
    cfg, targets = setup(gateway, ["@aaa_chat", "@bbb_chat"])
    gateway.send_plan["@aaa_chat"] = [Restricted("limited: check @SpamBot")]
    summary = run(plan_for(gateway, targets, cfg, rec), cfg, gateway, rec)
    assert statuses(summary) == [("@aaa_chat", FAILED), ("@bbb_chat", NOT_SENT)]
    assert "SpamBot" in summary.stopped and gateway.sent == []


def test_fatal_session_error_stops_the_run(gateway, rec):
    cfg, targets = setup(gateway, ["@aaa_chat", "@bbb_chat"])
    gateway.send_plan["@aaa_chat"] = [Fatal("session revoked")]
    summary = run(plan_for(gateway, targets, cfg, rec), cfg, gateway, rec)
    assert summary.stopped == "session revoked" and summary.count(NOT_SENT) == 1


def test_transient_errors_are_retried_with_backoff(gateway, rec):
    cfg, targets = setup(gateway, ["@aaa_chat"])
    gateway.send_plan["@aaa_chat"] = [Transient("network problem"), Transient("network problem")]
    summary = run(plan_for(gateway, targets, cfg, rec), cfg, gateway, rec)
    assert summary.results[0].status == SENT and rec.sleeps == [5, 10]


def test_transient_errors_eventually_fail_the_chat(gateway, rec):
    cfg, targets = setup(gateway, ["@aaa_chat", "@bbb_chat"])
    gateway.send_plan["@aaa_chat"] = [Transient("down")] * 5
    summary = run(plan_for(gateway, targets, cfg, rec), cfg, gateway, rec)
    assert statuses(summary) == [("@aaa_chat", FAILED), ("@bbb_chat", SENT)]


def test_unknown_gateway_errors_only_fail_that_chat(gateway, rec):
    cfg, targets = setup(gateway, ["@aaa_chat", "@bbb_chat"])
    gateway.send_plan["@aaa_chat"] = [NotFound("gone")]
    summary = run(plan_for(gateway, targets, cfg, rec), cfg, gateway, rec)
    assert statuses(summary) == [("@aaa_chat", FAILED), ("@bbb_chat", SENT)]


def test_keyboard_interrupt_stops_cleanly_and_keeps_what_was_sent(gateway, rec):
    cfg, targets = setup(gateway, ["@aaa_chat", "@bbb_chat", "@ccc_chat"])
    history = History(None)
    plan = plan_for(gateway, targets, cfg, rec, history)
    calls = {"n": 0}

    def interrupting_sleep(seconds):
        calls["n"] += 1
        if calls["n"] == 2:
            raise KeyboardInterrupt
        rec.sleep(seconds)

    summary = send_all(plan, "x", cfg, gateway, history, interrupting_sleep, rec.clock, lambda a, b: a, rec.say)
    assert summary.stopped == "interrupted by the user"
    assert summary.count(SENT) == 2 and summary.count(NOT_SENT) == 1
    assert len(history.sent) == 2


def test_message_options_are_passed_through(gateway, rec, tmp_path):
    cfg, targets = setup(gateway, ["@aaa_chat"], '[message]\nparse_mode = "html"\nlink_preview = true\nattachment = "pic.jpg"\n')
    run(plan_for(gateway, targets, cfg, rec), cfg, gateway, rec)
    sent = gateway.sent[0]
    assert sent["parse_mode"] == "html" and sent["preview"] is True and sent["attachment"].name == "pic.jpg"


def test_message_placeholders_are_filled_per_chat(gateway, rec):
    cfg, targets = setup(gateway, ["@aaa_chat", "@bbb_chat"])
    run(plan_for(gateway, targets, cfg, rec), cfg, gateway, rec, template="{title}|@{username}|{id}")
    assert gateway.sent[0]["text"].startswith("aaa_chat|@aaa_chat|")
    assert gateway.sent[1]["text"].startswith("bbb_chat|@bbb_chat|")


def test_skipped_items_appear_in_the_summary(gateway, rec):
    cfg, targets = setup(gateway, ["@aaa_chat"])
    targets.append(Target("@missing_chat"))
    summary = run(plan_for(gateway, targets, cfg, rec), cfg, gateway, rec)
    assert sorted(statuses(summary), key=lambda x: x[1]) == [("@aaa_chat", SENT), ("@missing_chat", SKIPPED)]
