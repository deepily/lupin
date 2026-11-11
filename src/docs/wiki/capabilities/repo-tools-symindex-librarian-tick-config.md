---
capability: repo-tools-symindex-librarian-tick-config
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.symindex.librarian_tick.read_value@648038d6db
  - cosa.repo.symindex.librarian_tick.read_create_cap@07366a14f6
  - cosa.repo.symindex.librarian_tick.read_enabled@48426a4325
  - cosa.repo.symindex.librarian_tick.read_persona@bfb1570e2a
  - cosa.repo.symindex.librarian_tick.read_mobile_corpus@3e5c46846d
  - cosa.repo.symindex.librarian_tick.crontab_command@1b83cbb8d8
  - cosa.repo.symindex.librarian_tick.install_moved_text@858db60dd5
  - cosa.repo.symindex.librarian_tick.install_command@48f4c13acd
  - cosa.repo.symindex.librarian_tick.cron_lines_for@f736281e58
  - cosa.repo.symindex.librarian_tick.cron_lines@ab28a46f8d
  - cosa.repo.symindex.librarian_tick.merge_lines@cd8b7c7098
  - cosa.repo.symindex.librarian_tick.load_crontab_lock@b5f0cfe1ba
  - cosa.repo.symindex.librarian_tick.edit_crontab@032f4b2309
  - cosa.repo.symindex.librarian_tick.status_text@e0e972f7d7
  - cosa.repo.symindex.librarian_tick.InstallRefused@9475ee3bd2
---
# Wiki librarian tick: switches and cron

How the tick ([[repo-tools-symindex-librarian-tick-run]]) reads its settings and installs its cron lines. The vector refresh job reuses the crontab helpers with its own tag.

## Settings
- `read_value( key, reader=None, errors=None )` reads one key from the configuration file fresh. It returns None for an absent or unreadable key, appends a read failure's message to `errors` and never raises.
- `read_enabled` is true only for `true`, `1`, `yes` or `on` in any case. Anything else, including an unreadable file, is false.
- `read_create_cap` takes `WIKI_LIBRARIAN_MAX_CREATES` from the environment when it is a positive integer, then the key `wiki librarian max creates per tick`, then 10.
- `read_persona( key, reader, default )` returns the stripped value or the default, `cheech` unless given. The keys are `wiki librarian owner persona` and `wiki librarian accountable manager`.
- `read_mobile_corpus` reads the lupin-mobile settings. A blank `wiki librarian mobile repo root` defaults to the `lupin-mobile` folder beside the checkout, and a missing folder returns None. The owner defaults to `tiffany`.

## Cron lines
- `cron_lines( root, python, log_path )` returns two lines. One is a daily line at `17 10 * * *`; the other is an `@reboot sleep 120 &&` line. Each ends with the tag `# wiki-librarian-tick`. It builds them with `cron_lines_for( run, schedule, boot_delay_seconds )`. That pairs a daily line with a reboot line for one command. The vector refresh passes 240 seconds.
- `merge_lines( current, lines, tag, legacy )` drops every line that ends with the tag (or one of a tuple of tags). It also drops any line holding a `legacy` substring. It puts the new ones last. Other lines keep their text and order. `status_text` answers `not installed`, `installed: n lines` for the expected count (2 by default), or `partly installed: n lines`.

## Installing
- `--print-install` prints the lines and changes nothing. `--install` is retired and prints `install_moved_text( root )`. One tool writes every Lupin cron line from the job registry, and the text gives its exact command. `install_command( root )` builds that command: the `cron_generate --install` line with its `cd` and environment. The branch guard's reinstall text reuses it. `--uninstall` goes through `edit_crontab`. `--status` only reads the crontab. The shared verb handler is `manage_cron` in [[repo-tools-symindex-librarian-tick-run]].
- `crontab_command( environ, own_variable )` picks the crontab command: `LUPIN_CRONTAB` when set, so one scratch crontab covers every tool, else the tool's own variable, else `crontab`.
- `edit_crontab( lines, environ, crontab_cmd, backup_dir, now, tag, owner, legacy )` holds the shared crontab lock, recorded under `owner`, for the whole read and write. `tag` and `legacy` go to `merge_lines`. It writes a timestamped backup first, and writes nothing if the backup fails. It raises `RuntimeError` on a failed crontab call or backup.
- `load_crontab_lock` loads `workflow/scripts/crontab_lock.py` from `PLANNING_IS_PROMPTING_ROOT`. When the variable is unset or the file is absent it raises `InstallRefused`, and nothing is written.
