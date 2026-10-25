---
capability: login-expiry-and-notify-probe
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.lib.claude_login_expiry.classify@7b615fecde
  - scripts.lib.claude_login_expiry.main@041b48268c
  - scripts.lib.installer_notify_probe.classify@9e0922ccf4
  - scripts.lib.installer_notify_probe.main@055c8e8847
---
# Login expiry and notify probe

Two small helpers the installer and preflight scripts call. Each prints one line and sets its exit code from what it found.

## Claude login expiry
- The test container keeps its own Claude Code login, and when it expires every Claude Code job there fails. The preflight reads one number from the credentials file, the expiry in milliseconds since the epoch.
- That number is the only part of the file the module sees, so no token is ever read.
- `claude_login_expiry.classify` returns `expired` or `valid` with an ISO time, by comparing the expiry with the current time. An expiry at or before now is expired.
- It returns `unreadable` with a reason unless the text is a positive whole number after trimming.
- `claude_login_expiry.main` prints exactly one line and returns 0 for valid, and 1 for expired or unreadable.

## Installer notify probe
- The cosa-voice installer used to print `fail` for every unsuccessful reply, hide stderr and exit 0. The probe sends one test notification and keeps the notifier's own status and message.
- `installer_notify_probe.classify` turns a notifier reply into an exit code and a one-line verdict. The line starts with `ok`, `skipped` or `fail`.
- Exit 0 means delivered, 3 means skipped because nobody is listening, and 1 means failed.
- `installer_notify_probe.main` runs the probe. It needs `LUPIN_ROOT` in the environment and a server URL argument.
