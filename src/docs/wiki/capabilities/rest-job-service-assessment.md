---
capability: rest-job-service-assessment
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.job_service.boot_time_from@b61bf5f184
  - cosa.rest.job_service.store_counts_from_rows@1c587a2e2f
  - cosa.rest.job_service.LiveDeps@d3145e67da
  - cosa.rest.job_service.assess_read@4bbc6599e7
  - cosa.rest.job_service.assess_target@996e91dc41
  - cosa.rest.job_service.worst@7295d96237
  - cosa.rest.job_service.assess_job@3f0f3b8c6c
  - cosa.rest.job_service.build_response@22d0eb1b20
---
# Jobs service: assessing every job

The service behind `GET /api/jobs/summary`. The registry is in [[rest-job-registry]], the rules in [[rest-job-health-rules]], the endpoints in [[rest-routers-job-summary-and-duplicate-check]], and Run now in [[rest-job-service-run-now]].

## Live inputs
- `boot_time_from` reads the `btime` line of `/proc/stat` and returns an aware local time. No such line raises `ValueError`.
- `store_counts_from_rows` counts a job's own rows. These are open now, opened in the window, closed in the window, and open at the window start. A row is closed when its status is one of `task_store_rules.TERMINAL_STATUSES` (done, dropped or wont_fix), as in the store.
- `LiveDeps` is the real input set. It reads boot time from `/proc/stat` and the installed crontab. It asks systemd for a unit state, then the host snapshot, then the service health address. The crontab and unit answers can come from the snapshot a host job writes when this process cannot ask.
- It names the host zone when the crontab came from the snapshot. It probes whether a run lock is held with a shared non-blocking lock, released at once. It counts store rows by the key prefix of the job, and answers `None`, never zero, when the store cannot be reached.

## Assessing
- `assess_read` probes the lock only for a job that has reported, and the store only for a job with a mark that has reported. It then calls `job_health.assess`.
- `assess_target` assesses one job or one target. A target without its own summary path reads the same summary file name inside a folder named for the target. A record that is unreadable or of a foreign schema reads as unknown with its own reason.
- `worst` picks the worst state among entries, using `lowest` of the candidate scorer. `assess_job` gives a job with targets the worst state of its targets, with each reason prefixed by the target name.
- `build_response` returns the schema, time, the jobs worst first then by title, and the count of jobs with reporting switched off with a one-line note. Cron hours are read in the crontab's zone, and overrides are read on each call. An unreadable registry raises.
