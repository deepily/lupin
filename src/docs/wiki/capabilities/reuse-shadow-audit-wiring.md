---
capability: reuse-shadow-audit-wiring
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_shadow.read_ceiling@392d981e88
  - lupin_mcp.reuse_shadow.read_lifetime_limit@a903473f1b
  - lupin_mcp.reuse_shadow.read_weekly_cap@9fb313d7f5
  - lupin_mcp.reuse_shadow.read_budgets_enabled@8b9dd2715f
  - lupin_mcp.reuse_shadow.check_lifetime_limit@e6b8f02438
  - lupin_mcp.reuse_shadow.live_capacity@3f7d917b5c
  - lupin_mcp.reuse_shadow.audit_inputs@d02f6f2200
  - lupin_mcp.reuse_shadow.queue_lookup@1316129eec
  - lupin_mcp.reuse_shadow.sweep_of@f2b1218847
  - lupin_mcp.reuse_shadow.drain@05b5be5ffb
  - lupin_mcp.reuse_shadow.cron_lines@074a604b39
  - lupin_mcp.reuse_shadow.main@cfb7766c77
---
# Reuse shadow audit wiring

`lupin_mcp.reuse_shadow` connects the shadow audit ([[repo-tools-candidate-shadow-audit-queue]]) to the live lookup and gives the drain a command line and a cron job. It is off until the INI key `reuse shadow audit enabled` is true. Five keys control it. Each is read fresh on every use, with no default and no Python constant. A missing, blank or garbled value refuses with a named error. It is never read as unlimited or as false.

## Queueing
- `check_exists_impl` offers each served lookup to `queue_lookup`, and a queue failure goes to stderr without changing the answer ([[reuse-tools-question-entry-points]]).
- `queue_lookup` returns the queue id, or None when the audit is off, the lookup is not sampled, or it is not a plain shortlist answer. Sweep-only, test-including, pair and excluded lookups are never queued. Neither is a lookup whose candidate stage failed.
- `audit_inputs( receipt )` reads the queue's fields from a stored receipt: need, language, generation, index sha and the live verdict with its candidate ids. It returns None for anything but a plain `check_exists` shortlist answer, which is how `queue_lookup` decides.
- The queued need is the receipt's query, which the redactor has already cleaned.

## Draining
- `read_ceiling` returns the token ceiling from `reuse shadow audit max tokens per drain`. A missing, blank, non-numeric or zero value raises `AUDIT_CEILING_UNSET`. `read_lifetime_limit` (`reuse shadow audit lifetime token limit`, shipped 100000000) and `read_weekly_cap` (`reuse shadow audit weekly cap`, shipped 4) read the same way through `_read_positive`. They raise `AUDIT_LIFETIME_UNSET` and `AUDIT_WEEKLY_CAP_UNSET`.
- `read_budgets_enabled` reads `reuse shadow audit budgets enabled`, exactly true or false. True applies the lifetime limit and the weekly cap. False reads and checks neither, the drain logs one line saying the budgets are off, and the per-drain ceiling still applies. Anything else raises `AUDIT_BUDGETS_SWITCH`.
- `check_lifetime_limit( ledger, limit, ceiling )` runs before any sweep. It adds up the Jev spend ledger's `shadow-audit-` runs with `held_by_prefix`, and raises `AUDIT_LIFETIME_REACHED` when that total plus the drain ceiling would pass the limit. A ledger it cannot read raises `AUDIT_LEDGER_UNREADABLE`. A refused drain spends nothing, leaves the queue alone and logs `drain refused`.
- `live_capacity( ledger )` runs `reuse_ledger.account_capacity` with the audit ceiling and weekly cap read from the drain's keys. The two cannot drift apart. `reuse_ledger` holds no audit constant.
- `sweep_of( ctx_factory, ask )` builds the sweep function. Each sweep gets a fresh packed context and its own run name. It returns the verdict, the shortlist ids and the tokens in plus out, and the cause when the verdict is uncertain. An error answer raises `AUDIT_SWEEP_REFUSED`.
- `drain` runs the queue through `run_pending` under that ceiling and returns its result with `spent_tokens` and `stopped_by`. It also stops at the weekly cap it is given. That is the INI value, or none when the budgets are off. The cap counts the last seven days, and `stopped_by` then reads `weekly_cap`. Known-miss items drain first, so a week with four known misses leaves no sample audits.
- The live drain needs the pack size variable, or it raises `AUDIT_NEEDS_PACKED`.

## Command and cron
- `cron_lines` builds a daily line at 11:37 and a reboot line, both running `src/scripts/reuse-shadow-audit.sh` and ending with the tag `# reuse-shadow-audit`.
- `main` drains once by default. `--print-install` shows the lines. `--install` is retired and prints the `cron_generate` command; `--uninstall` and `--status` use the librarian's locked crontab editor.
- Exit 0 means the drain ran or an install worked. Exit 1 means it failed or an install was refused. Exit 2 means a named error, such as a missing ceiling or a drain that would pass the lifetime limit. Exit 3 means the job is switched off.
