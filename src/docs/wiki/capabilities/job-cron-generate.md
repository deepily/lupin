---
capability: job-cron-generate
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.cron_generate.managed_jobs@ca82f9cb8f
  - lupin_mcp.cron_generate.lines_for_job@044de13325
  - lupin_mcp.cron_generate.generate@7e20676cd5
  - lupin_mcp.cron_generate.make_log_folders@484230930c
  - lupin_mcp.cron_generate.main@a8c0f68053
---
# Job cron generator

Writes the cron lines for the background jobs; see [[job-run-wrapper]] for what each line runs and [[job-host-snapshot]] for the crontab copy it reads.

## What it does
- Reads `src/conf/job-registry.json`. Jobs with `cron_managed` true get lines; the rest are left alone.
- `managed_jobs` raises ValueError for a managed job with no `cron_tag`, because its old lines could not be found again.
- It also raises for a job that is neither managed nor given a `cron_exclusion_reason`. This applies if the job runs, has a `cron_tag` or has a cron or after-boot schedule. No job is left out without a stated reason.
- `lines_for_job` returns one line per schedule entry with `cron` or `after_boot_seconds`. An `every_seconds` entry has no cron form and adds nothing.
- A cron line is `<schedule> <entry script> <job> cron >> <log> 2>&1 # <tag>`. A boot line starts `@reboot`, with `sleep <n> &&` when n is not 0, and ends in `boot`.
- A job with `cron_enabled` false gets no lines, but its tag stays in the block's tags, so an install still removes its old lines.
- The log defaults to `io/jobs/<job>/cron.log`; the registry's `cron_log` overrides it.
- `generate` returns the lines (header first), the tags the block owns and the legacy substrings from `cron_replaces`.
- `make_log_folders` creates each log's parent folder, because the shell opens the log before the job starts.

## Modes of `main`
- `--print` (default) writes the block and changes nothing. `--diff` writes the unified diff an install would make.
- `--status` says how many block lines are installed.
- `--install` and `--uninstall` use the librarian's locked crontab editor, with a timestamped backup under `io/jobs/crontab-backups` first. No backup, no write.
- A run that would change nothing writes no backup and no crontab, and says so.
- It returns 0, or 1 with the reason when the install is refused or fails.

## Don't
- Don't install from a Claude seat. A person runs `--install` from the main checkout.
- Don't edit the generated lines. Edit the registry.
