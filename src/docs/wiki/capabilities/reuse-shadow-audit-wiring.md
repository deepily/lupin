---
capability: reuse-shadow-audit-wiring
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_shadow.read_ceiling@c22b1dffd6
  - lupin_mcp.reuse_shadow.queue_lookup@41edf225f7
  - lupin_mcp.reuse_shadow.sweep_of@98d5f7e604
  - lupin_mcp.reuse_shadow.drain@6f786cc156
  - lupin_mcp.reuse_shadow.cron_lines@074a604b39
  - lupin_mcp.reuse_shadow.main@8af0b204d2
---
# Reuse shadow audit wiring

`lupin_mcp.reuse_shadow` connects the shadow audit ([[repo-tools-candidate-shadow-audit-queue]]) to the live lookup and gives the drain a command line and a cron job. It is off until the INI key `reuse shadow audit enabled` is true. Both keys are read fresh on every use.

## Queueing
- `check_exists_impl` offers each served lookup to `queue_lookup`, and a queue failure goes to stderr without changing the answer ([[reuse-tools-question-entry-points]]).
- `queue_lookup` returns the queue id, or None when the audit is off, the lookup is not sampled, or it is not a plain shortlist answer. Sweep-only, test-including, pair and excluded lookups are never queued. Neither is a lookup whose candidate stage failed.
- The queued need is the receipt's query, which the redactor has already cleaned.

## Draining
- `read_ceiling` returns the token ceiling from `reuse shadow audit max tokens per drain`. There is no default. A missing, blank, non-numeric or zero value raises `AUDIT_CEILING_UNSET`.
- `sweep_of( ctx_factory, ask )` builds the sweep function. Each sweep gets a fresh packed context and its own run name. It returns the verdict, the shortlist ids and the tokens in plus out, and the cause when the verdict is uncertain. An error answer raises `AUDIT_SWEEP_REFUSED`.
- `drain` runs the queue through `run_pending` under that ceiling and returns its result with `spent_tokens` and `stopped_by`.
- The live drain needs the pack size variable, or it raises `AUDIT_NEEDS_PACKED`.

## Command and cron
- `cron_lines` builds a daily line at 11:37 and a reboot line, both running `src/scripts/reuse-shadow-audit.sh` and ending with the tag `# reuse-shadow-audit`.
- `main` drains once by default. `--print-install` shows the lines. `--install`, `--uninstall` and `--status` use the librarian's locked crontab editor.
- Exit 0 means the drain ran or an install worked. Exit 1 means it failed or an install was refused. Exit 2 means a named error, such as a missing ceiling. Exit 3 means the job is switched off.
