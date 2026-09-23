# Changelog

## 1.0.0

First public release.

- Send one message to a list of your Telegram chats (channels and groups) from your account (Telethon).
- Guided `tgcast setup`; `check`, `send --dry-run`, `send`, `status`.
- Per-chat permission check, exact preview, confirmation before sending.
- History file: never posts twice to the same chat within the cooldown.
- Random pauses, batch rests, a hard per-run cap, FloodWait handling; stops on account limits.
- Personalised text placeholders, optional attachment, CSV report, summary to Saved Messages, delayed start with `--at`.
