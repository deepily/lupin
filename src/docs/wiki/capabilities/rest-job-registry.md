---
capability: rest-job-registry
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.job_registry.load_registry@2331e4912c
  - cosa.rest.job_registry.reporting_on@b552249ccd
  - cosa.rest.job_registry.load_overrides@b208e13540
  - cosa.rest.job_registry.effective@4f47d2d9ff
  - cosa.rest.job_registry.crontab_schedule@89dd95c36b
  - cosa.rest.job_registry.with_installed_schedule@11f2ffedb8
  - cosa.rest.job_registry.resolve_path@139ed813fa
---
# Job registry and run-time overrides

`src/conf/job-registry.json` lists every background job and is changed only by a reviewed commit, because a dead job cannot rewrite its own promise. Health is judged in [[rest-job-health-rules]]; the service that reads this is [[rest-job-service-assessment]].

## Loading
- `load_registry` reads the file and checks it. The schema must be `job-registry/1`, and each job needs an id, a title and an owner. Ids are unique and the owner must be a lowercase seat name, not a role label.
- Each schedule entry holds exactly one of `cron`, `after_boot_seconds` or `every_seconds`. Reporting, when present, is `on` or `off`, and `off` needs a reason. Any breach raises `ValueError`.
- `reporting_on` is false only for a job that says `off`. Switching reporting off hides the job from the list and the counts and does not stop it.

## Overrides
- `load_overrides` reads the small overrides file on every call, through `load_json_dict` ([[utils-atomic-json]]). It keeps only positive numbers for `grace_minutes` and `notify_interval_minutes`. A missing or broken file means no overrides, and one bad entry is dropped alone.
- `effective` resolves each of the two numbers by override, then the job, then the defaults, and returns a copy of the job.

## Installed schedule
- `crontab_schedule( text, tag )` reads the schedule off `crontab -l`. A five-field line ending in the tag becomes a cron entry. An `@reboot` line becomes a boot delay taken from its leading sleep, else 0. Commented-out lines are ignored.
- `with_installed_schedule` swaps in those lines for a job with a `cron_tag`. When the crontab is unreadable or has no tagged line, it keeps the registry schedule and marks it unverified.
- `resolve_path` fills a leading `{root}`, `{data}` or `{code_health}` in a registry path, and treats any other path as relative to the root.
