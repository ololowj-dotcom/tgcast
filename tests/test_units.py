import os
import stat
import sys

import pytest
from conftest import make_cfg

from tgcast.config import ConfigError, load_config, parse_config, parse_env_file
from tgcast.errors import Fatal, FloodWait, Forbidden, NotFound, Restricted, Transient
from tgcast.gateway import classify, map_error
from tgcast.models import Target
from tgcast.store import History
from tgcast.targets import normalize, parse_targets
from tgcast.template import CONFIG_TEMPLATE
from tgcast.templates import render, validate


@pytest.mark.parametrize("raw,expected", [
    ("@my_channel", "@my_channel"),
    ("my_channel", "@my_channel"),
    ("https://t.me/my_channel", "@my_channel"),
    ("http://t.me/my_channel/123", "@my_channel"),
    ("t.me/my_channel", "@my_channel"),
    ("telegram.me/My_Channel?start=x", "@My_Channel"),
    ("-1001234567890", "-1001234567890"),
    ("-12345", "-12345"),
])
def test_targets_are_normalised(raw, expected):
    assert normalize(raw) == (expected, "")


@pytest.mark.parametrize("raw,fragment", [
    ("https://t.me/+AbCdEfGh123", "invite links"),
    ("t.me/joinchat/AAAA", "invite links"),
    ("123456789", "user id"),
    ("@ab", "not a channel"),
    ("hello world!", "not a channel"),
    ("@1starts_with_digit", "not a channel"),
])
def test_bad_targets_are_explained(raw, fragment):
    ref, problem = normalize(raw)
    assert ref == "" and fragment in problem


def test_parse_targets_handles_comments_dupes_and_errors():
    text = "# my chats\n@Alpha_chat   # main one\n\nhttps://t.me/alpha_chat\n@beta_chat\nnot valid!\n-100123456\n"
    targets, errors = parse_targets(text)
    assert [t.ref for t in targets] == ["@Alpha_chat", "@beta_chat", "-100123456"]
    assert [t.line for t in targets] == [2, 5, 7]
    assert len(errors) == 1 and errors[0].startswith("line 6:")


def test_empty_targets_file():
    assert parse_targets("# nothing\n\n") == ([], [])


def test_render_fills_placeholders_and_keeps_literal_braces():
    ctx = {"title": "Devs", "username": "devs", "id": "5", "date": "2026-01-02"}
    assert render("Hi {title} ({username}/{id}) {date} {{literal}}", ctx) == "Hi Devs (devs/5) 2026-01-02 {literal}"
    assert render("  padded  ", ctx) == "padded"


def test_missing_context_values_become_empty():
    assert render("[{username}]", {"title": "x"}) == "[]"


def test_validate_reports_problems():
    assert validate("Hello {title}") == []
    assert "unknown placeholder {nmae}" in validate("Hi {nmae}")[0]
    assert validate("   ") == ["the message is empty"]
    assert "broken" in validate("Hi {title")[0]
    assert "unknown placeholder {0}" in validate("Hi {0}")[0]


def test_history_roundtrip_and_atomic_write(tmp_path):
    path = tmp_path / "sub" / "history.json"
    history = History.load(path)
    history.record_sent(-100, "Chat", 1000.0, 7)
    history.add_run({"time": 1000.0, "sent": 1})
    assert not list(path.parent.glob("*.tmp"))
    again = History.load(path)
    assert again.last_sent(-100) == 1000.0 and again.runs[0]["sent"] == 1 and again.last_sent(5) is None


def test_corrupt_history_is_quarantined(tmp_path):
    path = tmp_path / "history.json"
    path.write_text("{oops", encoding="utf-8")
    history = History.load(path)
    assert history.recovered and history.sent == {}
    assert (tmp_path / "history.json.corrupt").exists()


def test_history_keeps_only_recent_runs(tmp_path):
    history = History.load(tmp_path / "h.json")
    for i in range(80):
        history.add_run({"time": float(i)})
    assert len(history.runs) == 50 and history.runs[-1]["time"] == 79.0


def test_history_without_a_path_is_memory_only():
    history = History(None)
    history.record_sent(1, "x", 1.0, None)
    assert history.last_sent(1) == 1.0


def test_config_defaults_and_paths(tmp_path):
    cfg = make_cfg("", tmp_path)
    assert cfg.telegram.api_id == 12345 and cfg.telegram.session == tmp_path / "tgcast.session"
    assert cfg.limits.delay_min == 20 and cfg.limits.max_per_run == 20 and cfg.message.parse_mode == "markdown"
    assert cfg.message.file == tmp_path / "message.md" and cfg.report.csv is None


def test_config_env_interpolation_and_env_file(tmp_path):
    (tmp_path / ".env").write_text("TG_API_ID=777\nTG_API_HASH='hash value'\n", encoding="utf-8")
    (tmp_path / "tgcast.toml").write_text(CONFIG_TEMPLATE, encoding="utf-8")
    cfg = load_config(tmp_path / "tgcast.toml", env={})
    assert cfg.telegram.api_id == 777 and cfg.telegram.api_hash == "hash value"
    assert cfg.path == (tmp_path / "tgcast.toml").resolve()


def test_missing_env_var_is_named(tmp_path):
    (tmp_path / "tgcast.toml").write_text(CONFIG_TEMPLATE, encoding="utf-8")
    with pytest.raises(ConfigError) as info:
        load_config(tmp_path / "tgcast.toml", env={})
    assert "TG_API_ID" in str(info.value) and "TG_API_HASH" in str(info.value)


def test_real_environment_wins_over_the_env_file(tmp_path):
    (tmp_path / ".env").write_text("TG_API_ID=1\nTG_API_HASH=a\n", encoding="utf-8")
    (tmp_path / "tgcast.toml").write_text(CONFIG_TEMPLATE, encoding="utf-8")
    assert load_config(tmp_path / "tgcast.toml", env={"TG_API_ID": "2", "TG_API_HASH": "b"}).telegram.api_id == 2


def errors_of(toml_text):
    with pytest.raises(ConfigError) as info:
        make_cfg(toml_text)
    return str(info.value)


def test_unknown_keys_get_hints():
    assert "did you mean 'delay_min'" in errors_of("[limits]\ndelay_mn = 5")
    assert "unknown setting" in errors_of("[mesage]\nfile = 'x'")


def test_validation_messages():
    assert "must be >= 1" in errors_of("[limits]\ndelay_min = 0")
    assert "delay_min: must not be greater" in errors_of("[limits]\ndelay_min = 90\ndelay_max = 10")
    assert "split a big list" in errors_of("[limits]\nmax_per_run = 5000")
    assert "must be one of" in errors_of("[message]\nparse_mode = 'rtf'")
    assert "whole number" in errors_of("[limits]\nretries = 'many'")
    assert "true or false" in errors_of("[message]\nlink_preview = 'yes'")


def test_bad_credentials_are_explained():
    with pytest.raises(ConfigError) as info:
        parse_config({"telegram": {"api_id": "abc", "api_hash": ""}}, {}, __import__("pathlib").Path("."))
    assert "my.telegram.org" in str(info.value)


def test_config_file_errors(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.toml")
    bad = tmp_path / "bad.toml"
    bad.write_text("[telegram\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid TOML"):
        load_config(bad)


def test_parse_env_file(tmp_path):
    f = tmp_path / ".env"
    f.write_text("# c\nA=1\nexport B=\"x y\"\nbroken\n", encoding="utf-8")
    assert parse_env_file(f) == {"A": "1", "B": "x y"}


def named(name, **attrs):
    cls = type(name, (Exception,), {})
    exc = cls("boom")
    for key, value in attrs.items():
        setattr(exc, key, value)
    return exc


def test_error_mapping_by_name():
    flood = map_error(named("FloodWaitError", seconds=42))
    assert isinstance(flood, FloodWait) and flood.seconds == 42
    assert isinstance(map_error(named("SlowModeWaitError", seconds=9)), FloodWait)
    assert isinstance(map_error(named("PeerFloodError")), Restricted)
    assert "SpamBot" in str(map_error(named("PeerFloodError")))
    assert isinstance(map_error(named("AuthKeyUnregisteredError")), Fatal)
    assert isinstance(map_error(named("UsernameNotOccupiedError")), NotFound)
    assert isinstance(map_error(named("ChatWriteForbiddenError")), Forbidden)
    assert isinstance(map_error(named("ServerError")), Transient)
    assert isinstance(map_error(ConnectionResetError("x")), Transient)
    other = map_error(named("SomethingNewError"))
    assert isinstance(other, Forbidden) and "SomethingNewError" in str(other)
    same = Forbidden("x")
    assert map_error(same) is same


def test_error_mapping_with_real_telethon_classes():
    from telethon import errors

    flood = map_error(errors.FloodWaitError(request=None, capture=77))
    assert isinstance(flood, FloodWait) and flood.seconds == 77
    assert isinstance(map_error(errors.PeerFloodError(request=None)), Restricted)
    assert isinstance(map_error(errors.ChatWriteForbiddenError(request=None)), Forbidden)
    assert isinstance(map_error(errors.UsernameNotOccupiedError(request=None)), NotFound)
    assert isinstance(map_error(errors.SlowModeWaitError(request=None, capture=15)), FloodWait)


class Rights:
    def __init__(self, **flags):
        self.__dict__.update(flags)


def _make(name, attrs):
    cls = type(name, (), {})
    obj = cls()
    obj.__dict__.update(attrs)
    return obj


T = Target("@x_chat")


def test_classify_users_and_forbidden():
    user = classify(_make("User", {"first_name": "Ann", "last_name": "B"}), 5, T)
    assert user.kind == "user" and not user.can_post and user.title == "Ann B"
    assert not classify(_make("ChannelForbidden", {"title": "x"}), 5, T).can_post


def test_classify_broadcast_channels():
    plain = classify(_make("Channel", {"title": "News", "broadcast": True}), -100, T)
    assert plain.kind == "channel" and not plain.can_post and "admin" in plain.reason
    owner = classify(_make("Channel", {"title": "News", "broadcast": True, "creator": True}), -100, T)
    assert owner.can_post
    admin = classify(_make("Channel", {"title": "News", "broadcast": True, "admin_rights": Rights(post_messages=True)}), -100, T)
    assert admin.can_post
    no_post = classify(_make("Channel", {"title": "News", "broadcast": True, "admin_rights": Rights(post_messages=False)}), -100, T)
    assert not no_post.can_post


def test_classify_supergroups():
    ok = classify(_make("Channel", {"title": "Devs", "megagroup": True, "username": "devs"}), -100, T)
    assert ok.kind == "supergroup" and ok.can_post and ok.username == "devs"
    assert classify(_make("Channel", {"title": "D", "megagroup": True, "slowmode_enabled": True}), -1, T).slowmode
    assert not classify(_make("Channel", {"title": "D", "left": True}), -1, T).can_post
    assert "restricted" in classify(_make("Channel", {"title": "D", "banned_rights": Rights(send_messages=True)}), -1, T).reason
    locked = _make("Channel", {"title": "D", "default_banned_rights": Rights(send_messages=True)})
    assert not classify(locked, -1, T).can_post
    locked.admin_rights = Rights(post_messages=True)
    assert classify(locked, -1, T).can_post
    assert not classify(_make("Channel", {"title": "D", "restricted": True}), -1, T).can_post


def test_classify_basic_groups():
    assert classify(_make("Chat", {"title": "G"}), -5, T).can_post
    assert "deactivated" in classify(_make("Chat", {"title": "G", "deactivated": True}), -5, T).reason
    assert not classify(_make("Chat", {"title": "G", "left": True}), -5, T).can_post
    assert not classify(_make("Chat", {"title": "G", "default_banned_rights": Rights(send_messages=True)}), -5, T).can_post
    assert "unsupported" in classify(_make("Weird", {"title": "G"}), 1, T).reason


def test_title_falls_back_to_username_then_id():
    assert classify(_make("Chat", {"title": "", "username": "u"}), -5, T).title == "u"
    assert classify(_make("Chat", {}), -5, T).title == "-5"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes")
def test_env_and_session_modes(tmp_path):
    from conftest import FakeGateway, Recorder, runtime

    from tgcast.cli import main
    gw, rec = FakeGateway(), Recorder()
    rec.answers = ["+100000", "12345"]
    assert main(["setup", "--dir", str(tmp_path), "--api-id", "1", "--api-hash", "h"], runtime(gw, rec)) == 0
    assert stat.S_IMODE(os.stat(tmp_path / ".env").st_mode) == 0o600

