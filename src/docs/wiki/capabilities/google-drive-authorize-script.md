---
capability: google-drive-authorize-script
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.google-drive-authorize.run_flow@34c00b09ed
  - scripts.google-drive-authorize.write_token@ae1c9fc0e6
  - scripts.google-drive-authorize.verify@f7d513ff57
  - scripts.google-drive-authorize.main@cc45281b95
---
# Google Drive authorization script

`src/scripts/google-drive-authorize.py` is the one-time step an operator runs before turning on [[podcast-drive-publishing]]. Nothing in the app calls it.

## What it does
- `main` reads the Desktop-app OAuth client file `src/conf/keys/google-drive-oauth-client.json`. If it is missing, it prints how to create one, writes nothing and returns 2.
- `run_flow` opens the browser consent page for the `drive.file` scope and returns credentials with a refresh token.
- `write_token` saves them to `src/conf/keys/google-drive-oauth-token.json` with mode 600, even if the file existed with another mode.
- `verify` makes one real call: it reads the account email and lists up to ten of the app's own files. `main` prints the email and returns 0.

## Don't
- Don't copy or link the key files into a worktree. They are secrets.
