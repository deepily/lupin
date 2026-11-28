---
capability: login-expiry-and-notify-probe
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - scripts.lib.claude_login_expiry.classify@7b615fecde
  - scripts.lib.claude_login_expiry.classify_refresh@a5e3d411f8
  - scripts.lib.claude_login_expiry.refresh_main@b4362a80aa
  - scripts.lib.claude_login_expiry.main@041b48268c
  - scripts.lib.installer_notify_probe.classify@9e0922ccf4
  - scripts.lib.installer_notify_probe.main@ee6df01217
---
# Login expiry and notify probe

Two small helpers the installer, preflight and login-tick scripts call. Each sets its exit code from what it found.

## Claude login expiry
- The test container keeps its own Claude Code login, and when it expires every Claude Code job there fails. The preflight reads one number from the credentials file, the expiry in milliseconds since the epoch.
- That number is the only part of the file the module sees, so no token is ever read.
- `claude_login_expiry.classify` returns `expired` or `valid` with an ISO time, by comparing the expiry with the current time. An expiry at or before now is expired.
- It returns `unreadable` with a reason unless the text is a positive whole number after trimming.
- `claude_login_expiry.main` prints exactly one line and returns 0 for valid, and 1 for expired or unreadable.
- The refresh token has its own expiry, and `claude-login-tick.sh` checks it for the dev container. It passes only the token's length and expiry number, and calls no model.
- `classify_refresh` returns `blank` for an empty token, `lapsed` at or past the expiry, `soon` within `warn_days` (7), else `ok`. A token with no recorded expiry is `ok`.
- `refresh_main` runs for `--refresh <container> <length> <expiry>`. It is silent and returns 0 when ok. Otherwise it prints the finding and the login command, returning 2 for blank or lapsed and 3 for soon. `CLAUDE_LOGIN_WARN_DAYS` changes the window.

## Installer notify probe
- The cosa-voice installer used to print `fail` for every unsuccessful reply, hide stderr and exit 0. The probe sends one test notification and keeps the notifier's own status and message.
- `installer_notify_probe.classify` turns a notifier reply into an exit code and a one-line verdict. The line starts with `ok`, `skipped` or `fail`.
- Exit 0 means delivered, 3 means skipped because nobody is listening, and 1 means failed.
- `installer_notify_probe.main` runs the probe. It needs `LUPIN_ROOT` in the environment and a server URL argument.
