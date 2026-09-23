import csv
import datetime as dt
import sys

import pytest
from conftest import FakeGateway, Recorder, runtime

from tgcast import __version__
from tgcast.cli import build_parser, main
from tgcast.config import load_config
from tgcast.errors import Fatal, FloodWait, Restricted
from tgcast.store import History


def run_cli(argv, gateway, rec):
    return main(argv, runtime(gateway, rec))


def cfg_arg(project):
    return ["-c", str(project / "tgcast.toml")]


def ready(gateway, refs=("@alpha_chat", "@beta_chat", "@gamma_chat")):
    for ref in refs:
        gateway.add(ref)


def test_version_and_help(capsys):
    with pytest.raises(SystemExit) as info:
        main(["--version"])
    assert info.value.code == 0 and __version__ in capsys.readouterr().out
    assert main([]) == 0
    assert "setup" in capsys.readouterr().out


def test_every_command_parses():
    parser = build_parser()
    for argv in (["setup"], ["check"], ["send"], ["send", "--dry-run", "-y", "--force", "--limit", "3",
                                                 "--at", "2030-01-01 10:00"], ["status"]):
        assert parser.parse_args(argv).command


def test_setup_creates_everything_and_logs_in(tmp_path, gateway, rec):
    gateway.authorized = False
    rec.answers = ["+15550001", "24680"]
    rc = run_cli(["setup", "--dir", str(tmp_path / "out"), "--api-id", "12345", "--api-hash", "abcdef"], gateway, rec)
    assert rc == 0
    out = tmp_path / "out"
    assert sorted(p.name for p in out.iterdir()) == [".env", ".gitignore", "message.md", "targets.txt", "tgcast.toml"]
    assert gateway.login_calls == ["+15550001:24680"] and gateway.closed
    assert "TG_API_ID=12345" in (out / ".env").read_text() and "TG_API_HASH=abcdef" in (out / ".env").read_text()
    assert "*.session" in (out / ".gitignore").read_text() and ".env" in (out / ".gitignore").read_text()
    cfg = load_config(out / "tgcast.toml", env={})
    assert cfg.telegram.api_id == 12345 and cfg.telegram.api_hash == "abcdef"
    assert "Logged in as @tester" in rec.text and "tgcast check" in rec.text


def test_setup_with_two_step_password(tmp_path, gateway, rec):
    gateway.authorized = False
    gateway.needs_password = True
    rec.answers = ["+1", "111", "secret-pass"]
    assert run_cli(["setup", "--dir", str(tmp_path), "--api-id", "1", "--api-hash", "h"], gateway, rec) == 0
    assert "password:secret-pass" in gateway.login_calls


def test_setup_prompts_for_missing_values(tmp_path, gateway, rec):
    gateway.authorized = False
    rec.answers = ["555", "hashvalue", "+1", "42"]
    assert run_cli(["setup", "--dir", str(tmp_path)], gateway, rec) == 0
    assert "TG_API_ID=555" in (tmp_path / ".env").read_text()
    assert any("api_id" in q for q in rec.asked) and any("api_hash" in q for q in rec.asked)


def test_setup_skips_login_when_already_logged_in(tmp_path, gateway, rec):
    rec.answers = ["+1"]
    assert run_cli(["setup", "--dir", str(tmp_path), "--api-id", "1", "--api-hash", "h"], gateway, rec) == 0
    assert gateway.login_calls == [] and "Already logged in" in rec.text


def test_setup_keeps_existing_message_and_targets(tmp_path, gateway, rec):
    (tmp_path / "message.md").write_text("my text", encoding="utf-8")
    (tmp_path / "targets.txt").write_text("@mine_chat", encoding="utf-8")
    gateway.authorized = False
    rec.answers = ["+1", "1"]
    assert run_cli(["setup", "--dir", str(tmp_path), "--api-id", "1", "--api-hash", "h"], gateway, rec) == 0
    assert (tmp_path / "message.md").read_text() == "my text"
    assert (tmp_path / "targets.txt").read_text() == "@mine_chat"


def test_setup_refuses_to_overwrite_the_config_without_force(tmp_path, gateway, rec):
    (tmp_path / "tgcast.toml").write_text("# mine", encoding="utf-8")
    assert run_cli(["setup", "--dir", str(tmp_path), "--api-id", "1", "--api-hash", "h"], gateway, rec) == 1
    assert (tmp_path / "tgcast.toml").read_text() == "# mine"
    gateway.authorized = True
    assert run_cli(["setup", "--dir", str(tmp_path), "--api-id", "1", "--api-hash", "h", "--phone", "+1",
                    "--force"], gateway, rec) == 0
    assert "# mine" not in (tmp_path / "tgcast.toml").read_text()


def test_setup_validates_credentials(tmp_path, gateway, rec):
    assert run_cli(["setup", "--dir", str(tmp_path), "--api-id", "abc", "--api-hash", "h", "--phone", "+1"],
                   gateway, rec) == 1
    assert run_cli(["setup", "--dir", str(tmp_path), "--api-id", "1", "--api-hash", "", "--phone", "+1"],
                   gateway, rec) == 1
    assert not (tmp_path / "tgcast.toml").exists()


def test_setup_reports_login_failure_and_writes_nothing(tmp_path, gateway, rec):
    gateway.authorized = False
    gateway.login_error = Fatal("bad code")
    rec.answers = ["+1"]
    assert run_cli(["setup", "--dir", str(tmp_path), "--api-id", "1", "--api-hash", "h"], gateway, rec) == 1
    assert "Login failed: bad code" in rec.text and not (tmp_path / "tgcast.toml").exists() and gateway.closed


def test_dry_run_shows_plan_and_preview_but_sends_nothing(project, gateway, rec):
    ready(gateway)
    rc = run_cli(["send", "--dry-run", *cfg_arg(project)], gateway, rec)
    assert rc == 0 and gateway.sent == []
    assert "SEND  alpha_chat" in rec.text and "Message preview (as sent to alpha_chat)" in rec.text
    assert "Hello alpha_chat" in rec.text and "3 chat(s) will get the message" in rec.text
    assert "Dry run: nothing was sent." in rec.text and gateway.closed
    assert not (project / "history.json").exists()


def test_send_asks_for_confirmation(project, gateway, rec):
    ready(gateway)
    rec.answers = ["n"]
    assert run_cli(["send", *cfg_arg(project)], gateway, rec) == 1
    assert gateway.sent == [] and "Cancelled" in rec.text
    rec.answers = ["y"]
    assert run_cli(["send", *cfg_arg(project)], gateway, rec) == 0
    assert len(gateway.sent) == 3


def test_send_with_yes_and_history_and_run_log(project, gateway, rec):
    ready(gateway)
    assert run_cli(["send", "-y", *cfg_arg(project)], gateway, rec) == 0
    history = History.load(project / "history.json")
    assert len(history.sent) == 3 and history.runs[-1]["sent"] == 3
    assert "tgcast: sent 3, skipped 0, failed 0, not attempted 0" in rec.text and gateway.closed


def test_second_send_is_blocked_by_the_cooldown_and_force_overrides(project, gateway, rec):
    ready(gateway)
    run_cli(["send", "-y", *cfg_arg(project)], gateway, rec)
    gateway.sent.clear()
    rec2 = Recorder(rec.now + 60)
    assert run_cli(["send", "-y", *cfg_arg(project)], gateway, rec2) == 0
    assert gateway.sent == [] and "Nothing to send." in rec2.text and "already sent" in rec2.text
    rec3 = Recorder(rec.now + 120)
    assert run_cli(["send", "-y", "--force", *cfg_arg(project)], gateway, rec3) == 0
    assert len(gateway.sent) == 3


def test_limit_option(project, gateway, rec):
    ready(gateway)
    assert run_cli(["send", "-y", "--limit", "1", *cfg_arg(project)], gateway, rec) == 0
    assert len(gateway.sent) == 1


def test_exit_codes_for_failures_and_stops(project, gateway, rec):
    ready(gateway)
    gateway.send_plan["@beta_chat"] = [FloodWait(99999)]
    assert run_cli(["send", "-y", *cfg_arg(project)], gateway, rec) == 3
    assert "Stopped:" in rec.text
    gateway2 = FakeGateway()
    ready(gateway2)
    gateway2.send_plan["@alpha_chat"] = [Restricted("limited")]
    assert run_cli(["send", "-y", "--force", *cfg_arg(project)], gateway2, Recorder()) == 3
    gateway3 = FakeGateway()
    ready(gateway3)
    from tgcast.errors import Forbidden
    gateway3.send_plan["@alpha_chat"] = [Forbidden("no")]
    assert run_cli(["send", "-y", "--force", *cfg_arg(project)], gateway3, Recorder()) == 2


def test_csv_report_appends_rows(project, gateway, rec):
    ready(gateway, ["@alpha_chat", "@beta_chat"])
    (project / "targets.txt").write_text("@alpha_chat\n@beta_chat\n@missing_chat\n", encoding="utf-8")
    with (project / "tgcast.toml").open("a", encoding="utf-8") as handle:
        handle.write('[report]\ncsv = "out/report.csv"\n')
    run_cli(["send", "-y", *cfg_arg(project)], gateway, rec)
    rows = list(csv.reader((project / "out" / "report.csv").open(encoding="utf-8")))
    assert rows[0] == ["time", "target", "title", "status", "detail", "message_id"]
    assert sorted(r[3] for r in rows[1:]) == ["sent", "sent", "skipped"]
    gateway.sent.clear()
    run_cli(["send", "-y", "--force", *cfg_arg(project)], gateway, Recorder(rec.now + 5))
    assert len(list(csv.reader((project / "out" / "report.csv").open(encoding="utf-8")))) > len(rows)


def test_notify_self_sends_a_summary(project, gateway, rec):
    ready(gateway)
    with (project / "tgcast.toml").open("a", encoding="utf-8") as handle:
        handle.write("[report]\nnotify_self = true\n")
    run_cli(["send", "-y", *cfg_arg(project)], gateway, rec)
    assert gateway.self_messages and "sent 3" in gateway.self_messages[0]


def test_at_waits_until_the_given_time(project, gateway, rec):
    ready(gateway)
    moment = dt.datetime.fromtimestamp(rec.now + 100)
    assert run_cli(["send", "-y", "--at", moment.strftime("%Y-%m-%d %H:%M"), *cfg_arg(project)], gateway, rec) in (0, 1)
    assert "Waiting until" in rec.text or "in the past" in rec.text


def test_at_in_the_future_sleeps_in_small_steps_then_sends(project, gateway, rec):
    ready(gateway)
    future = dt.datetime.fromtimestamp(rec.now + 3600)
    assert run_cli(["send", "-y", "--at", future.strftime("%Y-%m-%d %H:%M"), *cfg_arg(project)], gateway, rec) == 0
    assert "Waiting until" in rec.text
    waits = [s for s in rec.sleeps[:200] if s > 1]
    assert max(waits) <= 30.0 and len(gateway.sent) == 3


def test_at_rejects_bad_or_past_times(project, gateway, rec, capsys):
    ready(gateway)
    assert run_cli(["send", "--at", "tomorrow", *cfg_arg(project)], gateway, rec) == 1
    assert "YYYY-MM-DD HH:MM" in capsys.readouterr().err
    assert run_cli(["send", "--at", "2000-01-01 10:00", *cfg_arg(project)], gateway, rec) == 1
    assert "in the past" in capsys.readouterr().err
    assert gateway.sent == []


def test_not_logged_in_is_a_clear_error(project, gateway, rec, capsys):
    gateway.authorized = False
    assert run_cli(["send", "-y", *cfg_arg(project)], gateway, rec) == 1
    assert "tgcast setup" in capsys.readouterr().err and gateway.closed


def test_config_problems_are_reported_not_raised(project, gateway, rec, capsys):
    (project / "message.md").write_text("Hi {nmae}", encoding="utf-8")
    assert run_cli(["send", *cfg_arg(project)], gateway, rec) == 1
    assert "unknown placeholder {nmae}" in capsys.readouterr().err
    (project / "message.md").write_text("ok", encoding="utf-8")
    (project / "targets.txt").write_text("@alpha_chat\nhttps://t.me/+secretinvite\n", encoding="utf-8")
    assert run_cli(["send", *cfg_arg(project)], gateway, rec) == 1
    assert "invite links" in capsys.readouterr().err
    (project / "targets.txt").write_text("# empty\n", encoding="utf-8")
    assert run_cli(["send", *cfg_arg(project)], gateway, rec) == 1
    assert "no chats yet" in capsys.readouterr().err
    (project / "targets.txt").unlink()
    assert run_cli(["send", *cfg_arg(project)], gateway, rec) == 1
    (project / "message.md").unlink()
    assert run_cli(["send", *cfg_arg(project)], gateway, rec) == 1
    assert run_cli(["send"], gateway, rec) in (0, 1)


def test_missing_attachment_is_reported(project, gateway, rec, capsys):
    with (project / "tgcast.toml").open("a", encoding="utf-8") as handle:
        handle.write('[message]\nattachment = "missing.jpg"\n')
    assert run_cli(["send", *cfg_arg(project)], gateway, rec) == 1
    assert "attachment not found" in capsys.readouterr().err


def test_check_lists_permissions_and_uses_exit_codes(project, gateway, rec):
    gateway.add("@alpha_chat")
    gateway.add("@beta_chat", can_post=False, reason="you are restricted in this group")
    rc = run_cli(["check", *cfg_arg(project)], gateway, rec)
    assert rc == 2
    assert "OK    alpha_chat" in rec.text and "beta_chat" in rec.text and "restricted" in rec.text
    assert "gamma_chat" in rec.text and "1 chat(s) ready, 2 with problems." in rec.text and gateway.sent == []
    gateway2 = FakeGateway()
    ready(gateway2)
    assert run_cli(["check", *cfg_arg(project)], gateway2, Recorder()) == 0


def test_check_ignores_the_cooldown_and_the_run_limit(project, gateway, rec):
    ready(gateway)
    run_cli(["send", "-y", *cfg_arg(project)], gateway, rec)
    rec2 = Recorder(rec.now + 10)
    assert run_cli(["check", *cfg_arg(project)], gateway, rec2) == 0
    assert "3 chat(s) ready" in rec2.text


def test_status(project, gateway, rec):
    assert run_cli(["status", *cfg_arg(project)], gateway, rec) == 0
    assert "No runs yet." in rec.text
    ready(gateway)
    run_cli(["send", "-y", *cfg_arg(project)], gateway, rec)
    rec2 = Recorder()
    assert run_cli(["status", *cfg_arg(project)], gateway, rec2) == 0
    assert "sent 3, skipped 0, failed 0" in rec2.text and "3 chat(s) have received" in rec2.text


def test_status_shows_stops(project, gateway, rec):
    ready(gateway)
    gateway.send_plan["@alpha_chat"] = [Restricted("limited")]
    run_cli(["send", "-y", *cfg_arg(project)], gateway, rec)
    rec2 = Recorder()
    run_cli(["status", *cfg_arg(project)], gateway, rec2)
    assert "stopped: limited" in rec2.text


def test_missing_config_message(tmp_path, gateway, rec, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert run_cli(["check"], gateway, rec) == 1
    assert "tgcast setup" in capsys.readouterr().err
    assert run_cli(["check", "-c", "nope.toml"], gateway, rec) == 1


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_secret_files_are_private(tmp_path, gateway, rec):
    import os
    import stat
    rec.answers = ["+1", "1"]
    gateway.authorized = False
    run_cli(["setup", "--dir", str(tmp_path), "--api-id", "1", "--api-hash", "h"], gateway, rec)
    assert stat.S_IMODE(os.stat(tmp_path / ".env").st_mode) == 0o600
