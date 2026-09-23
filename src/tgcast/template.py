from __future__ import annotations

CONFIG_TEMPLATE = """\
# tgcast configuration. Check it any time with:  tgcast check
# Secrets (api_id, api_hash) live in the .env file next to this file.

[telegram]
api_id = "${TG_API_ID}"
api_hash = "${TG_API_HASH}"
session = "tgcast.session"            # your login; never share or commit it

[message]
file = "message.md"                   # the text to send; {title} {username} {id} {date} are filled in per chat
parse_mode = "markdown"               # markdown | html | none
# attachment = "banner.jpg"           # optional picture or file sent with the text
link_preview = false

[targets]
file = "targets.txt"                  # one channel/group per line

[limits]
delay_min = 20                        # seconds between two messages (random between min and max)
delay_max = 60
batch_size = 10                       # after this many messages...
batch_pause = 300                     # ...rest this many seconds (0 = never)
max_per_run = 20                      # never send more than this in one run
cooldown_hours = 24                   # never post to the same chat twice within this time
flood_wait_max = 300                  # if Telegram asks to wait longer than this, stop the run
retries = 2

[report]
# csv = "report.csv"                  # append one line per chat to this file
notify_self = false                   # send a summary to your "Saved Messages"
"""

MESSAGE_TEMPLATE = """\
Hello, {title}!

Write your announcement here. Formatting follows the parse_mode from tgcast.toml
(Markdown: **bold**, __italic__, [link](https://example.com)).
"""

TARGETS_TEMPLATE = """\
# One chat per line: @username, a t.me link or a numeric chat id (-100...).
# tgcast only writes to chats you are already a member of and may post in.
# Text after # is ignored.
#
# @my_channel
# https://t.me/my_group
# -1001234567890
"""

GITIGNORE_TEMPLATE = """\
.env
*.session
*.session-journal
history.json*
report.csv
"""

ENV_TEMPLATE = """\
TG_API_ID={api_id}
TG_API_HASH={api_hash}
"""
