---
capability: repo-tools-symindex-librarian-tick-config
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.symindex.librarian_tick.read_value@648038d6db
  - cosa.repo.symindex.librarian_tick.read_create_cap@07366a14f6
  - cosa.repo.symindex.librarian_tick.read_enabled@48426a4325
  - cosa.repo.symindex.librarian_tick.read_persona@49b37e40f0
  - cosa.repo.symindex.librarian_tick.cron_lines@8e578a387c
  - cosa.repo.symindex.librarian_tick.merge_lines@029adb24e5
  - cosa.repo.symindex.librarian_tick.load_crontab_lock@b5f0cfe1ba
  - cosa.repo.symindex.librarian_tick.edit_crontab@0df0429592
  - cosa.repo.symindex.librarian_tick.status_text@09c14721a4
  - cosa.repo.symindex.librarian_tick.InstallRefused@9475ee3bd2
---
# Wiki librarian tick: switches and cron

How the tick ([[repo-tools-symindex-librarian-tick-run]]) reads its settings and installs its cron lines. The vector refresh job reuses the crontab helpers with its own tag.

## Settings
- `read_value( key, reader=None, errors=None )` reads one key from the configuration file fresh. It returns None for an absent or unreadable key, appends a read failure's message to `errors` and never raises.
- `read_enabled` is true only for `true`, `1`, `yes` or `on` in any case. Anything else, including an unreadable file, is false.
- `read_create_cap` takes `WIKI_LIBRARIAN_MAX_CREATES` from the environment when it is a positive integer, then the key `wiki librarian max creates per tick`, then 10.
- `read_persona` returns the stripped value or `cheech`. The keys are `wiki librarian owner persona` and `wiki librarian accountable manager`.

## Cron lines
- `cron_lines( root, python, log_path )` returns a daily line at `17 10 * * *` and an `@reboot sleep 120 &&` line. Each ends with the tag `# wiki-librarian-tick`.
- `merge_lines( current, lines, tag )` drops every tagged line from a crontab text and puts the new ones last. Untagged lines keep their text and order.
- `status_text` answers `not installed`, `installed: 2 lines`, or `partly installed: n lines` for any other count.

## Installing
- `--print-install` prints the lines and changes nothing. `--install` and `--uninstall` go through `edit_crontab`. `--status` only reads the crontab and prints the status text.
- `edit_crontab( lines, environ, crontab_cmd, backup_dir, now )` holds the shared crontab lock for the whole read and write. It writes a timestamped backup first, and writes nothing if the backup fails. It raises `RuntimeError` on a failed crontab call or backup.
- `load_crontab_lock` loads `workflow/scripts/crontab_lock.py` from `PLANNING_IS_PROMPTING_ROOT`. When the variable is unset or the file is absent it raises `InstallRefused`, and nothing is written.
