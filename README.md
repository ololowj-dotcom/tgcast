# tgcast

[![CI](https://github.com/ololowj-dotcom/tgcast/actions/workflows/ci.yml/badge.svg)](https://github.com/ololowj-dotcom/tgcast/actions/workflows/ci.yml)
![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)
![License MIT](https://img.shields.io/badge/license-MIT-green)
[![Download for Windows](https://img.shields.io/badge/download-Windows%20.exe-0078D6?logo=windows)](https://github.com/ololowj-dotcom/tgcast/releases/latest)

> **On Windows? There is a ready-made program, no Python needed.** Download
> [`tgcast-windows.zip`](https://github.com/ololowj-dotcom/tgcast/releases/latest), unpack it and double-click
> `tgcast.exe`: a menu guides you through setup and sending. Details in [Install](#install).

**Mailing to your base of Telegram chats.** You keep a base (a simple list) of your channels and groups in a text file,
write one message, and tgcast posts it to every chat in the base from your Telegram account, one by one - with safe
pauses and limits, and never twice to the same chat. The base can be as long as you like; it is worked through over
several runs.

Typical uses: announcing an event, a release or an offer in all the communities you run; posting the same update to
several groups you manage; sharing news with partner chats that agreed to receive it.

*[Читать по-русски](README.ru.md)*

## How it works, in plain words

1. **You log in once.** tgcast asks for your phone number and the code Telegram sends you, exactly like logging in to a
   new device. From then on it acts as **your account** and keeps the login in a file called `tgcast.session`.
2. **You give it two things:** a text file with the message and a text file with the list of chats.
3. **It checks every chat.** For each one it looks up whether you are a member and allowed to write there.
4. **You see the plan** (which chats will get the message, which are skipped and why, the exact text) and confirm.
5. **It sends one by one**, with random pauses, and writes every send into a history file so nothing is posted twice.

## What tgcast does and does not do

| It does | It does not |
|---|---|
| Post as your account in chats where you are **already a member** and allowed to write | Join chats for you |
| Post in a channel only if you are an admin with the right to publish | Write to individual people (private messages) |
| Skip chats you cannot write to, and tell you why | Collect or scrape members, or find chats on its own |
| Wait between messages, rest between batches, stop at a per-run cap | Send faster or in bulk beyond the limits you configure |
| Stop the run when Telegram says the account is limited | Work with several accounts or hide who is sending |
| Never post to the same chat again within the cooldown (24 h by default) | Bypass Telegram's rules or captchas |

tgcast is meant for announcements in communities **you run or are allowed to post in**: your channels and groups,
partner chats that agreed. Mass unsolicited messages break Telegram's terms and get accounts limited; the limits above
are there to keep this tool from turning into that.

## Which account to use

The tool logs in to a real account, so that account carries the risk. Telegram may limit an account that posts a lot of
identical text, especially into chats that did not ask for it.

- **Your own channels and groups:** your main account is fine.
- **Chats of other people (partners, communities):** use a **separate account** for it, not your main one, and only
  where posting announcements is allowed.

## Install

**Windows, the easy way (no Python needed):** download `tgcast-windows.zip` from the
[latest release](https://github.com/ololowj-dotcom/tgcast/releases/latest), unpack it, put `tgcast.exe` into an empty
folder for your mailing and **double-click it**. A menu opens: 1 setup, 2 check, 3 preview, 4 send, 5 history. Everything
below works the same; the menu simply runs those commands for you. Windows SmartScreen may warn that the program is not
signed: click "More info" -> "Run anyway". The file is built from this repository by GitHub Actions, and
`SHA256SUMS.txt` lets you check it.

**With Python (any system):**

```bash
pip install git+https://github.com/ololowj-dotcom/tgcast
```

Python 3.9 or newer. On Windows, install Python from python.org first (tick "Add to PATH"), then run the command in
PowerShell. Running `tgcast` with no arguments opens the same menu.

## Step by step

1. **Get an api_id and api_hash** (once): sign in at https://my.telegram.org, open *API development tools*, create an
   application (any name), and copy the two values. They identify your app to Telegram; keep them private.
2. **Create a folder** for the announcement and run the setup inside it:

   ```bash
   mkdir my-announcement && cd my-announcement
   tgcast setup
   ```

   It asks for the api_id, api_hash and your phone number in international format (`+1...`). Telegram sends you a
   login code **inside the Telegram app** (a message from "Telegram"); type it in. If the account has two-step
   verification, it asks for that password too. It then creates `tgcast.toml`, `message.md`, `targets.txt`, `.env` and a
   `.gitignore` that keeps your secrets out of git.
3. **Write the message** in `message.md`. Placeholders such as `{title}` are filled in per chat (see below).
4. **List the chats** in `targets.txt`, one per line: `@username`, a `t.me/...` link, or a numeric chat id. Text after
   `#` is ignored.
5. **Check:** `tgcast check` shows each chat and whether you can post there.
6. **Preview:** `tgcast send --dry-run` shows the plan and the exact text for the first chat. Nothing is sent.
7. **Send:** `tgcast send` shows the plan again, asks "Send to N chat(s) now?", and only then starts.

Finding a chat id: open the chat in Telegram Web (web.telegram.org); the number after `#` in the address bar is the id.
For channels and supergroups it starts with `-100`. If in doubt, use the chat's `@username` or `t.me` link instead.

## The message

`message.md` is plain text in the format set by `parse_mode` (Markdown by default: `**bold**`, `__italic__`,
`[link](https://example.com)`). These placeholders are filled in for every chat:

| Placeholder | Value |
|---|---|
| `{title}` | the chat's title |
| `{username}` | its @username (empty if it has none) |
| `{id}` | its numeric id |
| `{date}` | today's date, `YYYY-MM-DD` |

Use `{{` and `}}` for literal braces. To send a picture or a file with the text, add `attachment = "banner.jpg"` under
`[message]` in `tgcast.toml`; the text becomes its caption.

## How long does it take?

With the default settings the pauses between messages average 40 seconds, plus a 5-minute rest after every 10th
message, and a run sends to at most 20 chats:

| Chats in one run | Time |
|---|---|
| 5 | about 3 minutes |
| 10 | about 6 minutes |
| 20 | about 17 minutes |

`tgcast send` shows the estimate before it asks for confirmation. Keep the window open while it runs; Ctrl+C stops it
cleanly and everything already sent stays recorded.

## A big base of chats

The base is the `targets.txt` file: one chat per line, as many lines as you need. A run sends to at most `max_per_run`
chats (20 by default); the rest of the base waits. Simply run `tgcast send` again later: chats
that already got the message are skipped, and the next ones are taken.

**Important for a one-time announcement:** the "never twice" protection lasts `cooldown_hours` (24 by default). If your
list takes several days, chats you served on day one become eligible again on day two. For a one-off campaign set a long
cooldown in `tgcast.toml`, for example `cooldown_hours = 720` (30 days), and each chat is contacted once.

To run without sitting at the computer, `--yes` skips the confirmation (`tgcast send --yes`) and can be started from
Task Scheduler (Windows) or cron (Linux/macOS). `tgcast send --at "2026-10-01 10:00"` waits until that local time.

## Settings that keep you safe

All in `tgcast.toml`, section `[limits]`:

| Setting | Default | Meaning |
|---|---|---|
| `delay_min`, `delay_max` | 20, 60 | random pause in seconds between two messages |
| `batch_size`, `batch_pause` | 10, 300 | after this many messages, rest this many seconds |
| `max_per_run` | 20 | never send more than this in one run (500 is the hard ceiling) |
| `cooldown_hours` | 24 | never post to the same chat twice within this time |
| `flood_wait_max` | 300 | if Telegram asks to wait longer than this, the run stops |
| `retries` | 2 | tries after a short wait or a network problem |

Mistakes in the settings are reported with a hint (`unknown setting 'delay_mn' (did you mean 'delay_min'?)`).

## Commands

| Command | Purpose |
|---|---|
| `tgcast setup` | log in and create the files |
| `tgcast check` | validate everything and show which chats you can post to (exit code 2 if some cannot) |
| `tgcast send` | send; `--dry-run` preview only, `-y` no confirmation, `--force` ignore the cooldown, `--limit N`, `--at "2026-10-01 10:00"` |
| `tgcast status` | recent runs and how many chats have received the message |

Exit codes of `send`: `0` all done, `2` some chats failed, `3` the run was stopped (Telegram limits, session lost,
Ctrl+C), `1` configuration problem. Optional: `[report]` in `tgcast.toml` can append every result to a CSV file
(`csv = "report.csv"`) and send a summary to your Saved Messages (`notify_self = true`).

## If something goes wrong

| What you see | What it means and what to do |
|---|---|
| The login code does not arrive | Look in the Telegram app for a chat called "Telegram" (not SMS). Wait a minute, then run `tgcast setup` again |
| `no such chat or username` | Check the spelling. Private chats have no username: use the numeric id, and you must be a member |
| `you are not a member of this chat` | Join the chat yourself first; tgcast never joins for you |
| `you are restricted in this group` / `sending is disabled for members` | The chat does not let you write. Ask an admin, or remove it from the list |
| `Telegram asks to wait Ns` | Telegram's rate limit. Short waits are waited out automatically; longer than `flood_wait_max` stops the run: try later |
| `PeerFlood` / "account is limited" | Telegram limited the account. tgcast stops. Do not retry: check the account with @SpamBot in Telegram, wait a day or two, and lower the volume |
| `the Telegram session is no longer valid` | The login was ended (or the account is banned). Run `tgcast setup` again |
| `already sent ... (cooldown ...)` | The chat got the message recently. Wait, raise or lower `cooldown_hours`, or use `--force` deliberately |

## Your login

`tgcast.session` **is your Telegram login**. Anyone holding it can act as you: never share it, never commit it (the
generated `.gitignore` excludes it). If it leaks, end that session in Telegram under Settings -> Devices.

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
