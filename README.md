# tgcast

[![CI](https://github.com/ololowj-dotcom/tgcast/actions/workflows/ci.yml/badge.svg)](https://github.com/ololowj-dotcom/tgcast/actions/workflows/ci.yml)
![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)
![License MIT](https://img.shields.io/badge/license-MIT-green)

**Careful Telegram announcements to your own channels and groups.** You list the chats, write the text, look at a
preview, and tgcast posts it as your account - slowly, within limits, and never twice to the same chat.

*[Читать по-русски](README.ru.md)*

- **See before you send.** `tgcast send --dry-run` shows every chat, whether you may post there, and the exact message.
- **Permission-aware.** For each chat it checks that you are a member and allowed to write (or admin in a channel) and
  skips the rest with a reason, instead of failing halfway.
- **Never repeats itself.** A history file remembers where the message went; the same chat is skipped for
  `cooldown_hours` (24 by default).
- **Slow on purpose.** Random pauses, a longer rest every batch, a hard cap per run, and it obeys Telegram's
  FloodWait requests.
- **Stops when it should.** If Telegram says your account is limited, or asks for a very long wait, the run ends and
  tells you what to do, instead of pushing on.
- **Easy.** `tgcast setup` logs in and creates the files. Personalised text (`{title}`, `{date}`), an optional picture,
  a CSV report, a summary to your Saved Messages, and `--at` to send later.

## Responsible use

tgcast is for announcements to communities **you run or are allowed to post in**: your channels, your groups, partner
chats that agreed. It is deliberately limited: it never joins chats, never writes to individual users, never scrapes
members and works with one account. Bulk unsolicited messages break Telegram's terms and get accounts limited; that is
not what this tool is for, and its limits are there to keep it that way.

## Install

```bash
pip install git+https://github.com/ololowj-dotcom/tgcast
```

Python 3.9 or newer. On Windows, install Python from python.org first (tick "Add to PATH"), then run the command in
PowerShell.

## Quick start

1. Get an **api_id** and **api_hash** once at https://my.telegram.org (API development tools).
2. Make a folder for the announcement and run the guided setup inside it:

   ```bash
   mkdir my-announcement && cd my-announcement
   tgcast setup
   ```

   It asks for the api_id, api_hash and your phone number, logs you in (the code arrives in Telegram) and creates
   `tgcast.toml`, `message.md`, `targets.txt`, `.env` and a `.gitignore` that keeps your secrets out of git.
3. Put your text in `message.md` and your chats in `targets.txt` (one `@username`, t.me link or chat id per line).
4. Check, preview, send:

   ```bash
   tgcast check            # which chats can you post to?
   tgcast send --dry-run   # the plan and the exact message, nothing is sent
   tgcast send             # asks for confirmation, then sends
   ```

## The message

`message.md` is plain text in the format set by `parse_mode` (Markdown by default). These placeholders are filled in
for every chat:

| Placeholder | Value |
|---|---|
| `{title}` | the chat's title |
| `{username}` | its @username (empty for private chats) |
| `{id}` | its numeric id |
| `{date}` | today's date, `YYYY-MM-DD` |

Use `{{` and `}}` for literal braces. Add a picture or file with `attachment = "banner.jpg"` in `[message]`.

## Limits and safety settings

All in `tgcast.toml`, `[limits]`:

| Setting | Default | Meaning |
|---|---|---|
| `delay_min`, `delay_max` | 20, 60 | random pause in seconds between two messages |
| `batch_size`, `batch_pause` | 10, 300 | after this many messages, rest this many seconds |
| `max_per_run` | 20 | never send more than this in one run (the rest waits for the next run) |
| `cooldown_hours` | 24 | never post to the same chat twice within this time |
| `flood_wait_max` | 300 | if Telegram asks to wait longer than this, the run stops |
| `retries` | 2 | tries after a short wait or a network problem |

Configuration mistakes are reported with a hint (`unknown setting 'delay_mn' (did you mean 'delay_min'?)`).

## Commands

| Command | Purpose |
|---|---|
| `tgcast setup` | log in and create the files |
| `tgcast check` | validate everything and show which chats you can post to (exit code 2 if some cannot) |
| `tgcast send` | send; `--dry-run` preview only, `-y` no confirmation, `--force` ignore the cooldown, `--limit N`, `--at "2026-10-01 10:00"` |
| `tgcast status` | recent runs and how many chats have received the message |

Exit codes of `send`: `0` all done, `2` some chats failed, `3` the run was stopped (Telegram limits, session lost,
Ctrl+C), `1` configuration problem.

## Your login

`tgcast.session` **is your Telegram login**. Anyone holding it can act as you: never share it, never commit it (the
generated `.gitignore` excludes it). If it leaks, end the session in Telegram under Settings -> Devices.

## Development

```bash
git clone https://github.com/ololowj-dotcom/tgcast && cd tgcast
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest && ruff check src tests
```

The tests never contact Telegram: a scripted fake stands in for it, including FloodWait, PeerFlood, forbidden chats
and network errors, and the Telethon layer is exercised against a fake client using Telethon's real exception classes.
CI runs on Python 3.9-3.13.

## License

MIT - see [LICENSE](LICENSE).
