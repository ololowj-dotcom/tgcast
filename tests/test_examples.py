from pathlib import Path

from tgcast.config import load_config
from tgcast.targets import parse_targets
from tgcast.template import CONFIG_TEMPLATE, MESSAGE_TEMPLATE, TARGETS_TEMPLATE
from tgcast.templates import validate

ROOT = Path(__file__).resolve().parent.parent
ENV = {"TG_API_ID": "1", "TG_API_HASH": "h"}


def test_example_config_is_valid():
    cfg = load_config(ROOT / "examples" / "tgcast.example.toml", env=ENV)
    assert cfg.limits.max_per_run == 15 and cfg.report.notify_self is True
    assert cfg.message.attachment.name == "banner.jpg"


def test_example_message_and_targets_are_valid():
    assert validate((ROOT / "examples" / "message.md").read_text(encoding="utf-8")) == []
    targets, errors = parse_targets((ROOT / "examples" / "targets.txt").read_text(encoding="utf-8"))
    assert [t.ref for t in targets] == ["@my_channel", "@my_group", "-1001234567890"] and errors == []


def test_generated_templates_are_valid(tmp_path):
    (tmp_path / "tgcast.toml").write_text(CONFIG_TEMPLATE, encoding="utf-8")
    load_config(tmp_path / "tgcast.toml", env=ENV)
    assert validate(MESSAGE_TEMPLATE) == []
    assert parse_targets(TARGETS_TEMPLATE) == ([], [])
