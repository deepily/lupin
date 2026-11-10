---
capability: rest-job-cron-schedules
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.job_cron.parse_field@1f3a2d9f21
  - cosa.rest.job_cron.parse_cron@677dbcf259
  - cosa.rest.job_cron.day_matches@e3fd05ade9
  - cosa.rest.job_cron.moments@a6753a275b
  - cosa.rest.job_cron.cron_last@c216232fba
  - cosa.rest.job_cron.cron_next@3f618f4d10
  - cosa.rest.job_cron.cron_between@980902242f
  - cosa.rest.job_cron.entry_label@14e7aede7d
  - cosa.rest.job_cron.entry_last_due@31cc16c4f4
  - cosa.rest.job_cron.entry_next_due@ec8da5dd43
---
# Cron lines and schedule entries

Reads a job's schedule against a clock the caller passes in; nothing here reads the clock. The health rules that use it are in [[rest-job-health-rules]], and the registry that holds the entries is in [[rest-job-registry]].

## Reading a cron line
- `parse_field` expands one field (a comma list of `*`, `N`, `A-B`, each with an optional `/step`) into its sorted values. A bad step, an empty list or a value out of range raises `ValueError`.
- `parse_cron` needs exactly five fields and returns minutes, hours, days, months and weekdays. Sunday is 0 and a 7 folds to 0. It also records whether the day-of-month and the day-of-week were restricted.
- `day_matches` tests one date. When both day fields are restricted, either one matching is enough, as in standard cron. Otherwise both must match.
- `moments` lists the times a line fires on one date, earliest first.

## Finding firings
- `cron_last` gives the latest firing not after now, and `cron_next` the earliest after now. Both search 400 days and return `None` if nothing fires in that span. Now must carry a time zone.
- `cron_between( text, start, end )` lists the firings with start before the time and the time at or before end.

## Schedule entries
- An entry holds exactly one of `cron`, `after_boot_seconds` or `every_seconds`.
- `entry_label` names an entry in one line, such as `cron 0 10 * * * (daily)`, adding its mode in brackets when it has one.
- `entry_last_due` and `entry_next_due` say when an entry last came due and next comes due. A boot delay is due that many seconds after boot, and is past once. An interval entry is due one interval after the last attempt began, and is due now if there was no attempt.

## Don't
- Don't pass a naive datetime. The comparisons need aware times.
