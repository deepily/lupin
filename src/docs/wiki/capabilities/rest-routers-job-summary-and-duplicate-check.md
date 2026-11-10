---
capability: rest-routers-job-summary-and-duplicate-check
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.routers.job_summary.live_deps@656d9dfb40
  - cosa.rest.routers.job_summary.clock@f5fed70979
  - cosa.rest.routers.job_summary.jobs_summary@f5e91b0bff
  - cosa.rest.routers.job_summary.run_job_now@058084ebd7
  - cosa.rest.routers.duplicate_check_status.runs_folder@3f8453be3f
  - cosa.rest.routers.duplicate_check_status.installed_crontab@98279af0ba
  - cosa.rest.routers.duplicate_check_status.snapshot_now@b9cf8629b9
  - cosa.rest.routers.duplicate_check_status.now@7a3baafbcd
  - cosa.rest.routers.duplicate_check_status.get_status@f28fbf7f76
  - cosa.rest.routers.duplicate_check_status.get_job_summary@e0fd790c01
  - cosa.rest.routers.duplicate_check_status.get_page@536b7bfbfc
---
# Jobs and duplicate-check status endpoints

Two small routers over the job service in [[rest-job-service-assessment]] and [[rest-job-service-run-now]].

## Background jobs
- `live_deps` builds the root, the data folder (an environment variable first) and the live inputs. `clock` returns the aware local time. Tests replace both.
- `jobs_summary`, `GET /api/jobs/summary`, needs an API key or login. It returns the service's answer plus `caller_is_operator`, true only for the operator login. An unusable registry is a 500 with the cause.
- `run_job_now`, `POST /api/jobs/{job}/run`, is 403 for anyone but the operator login, and an API-key caller has no login. It checks that before reading the registry. Otherwise it returns the status and body of `run_now`.

## Duplicate check
- The three routes read only the run history of the daily check, which holds counts, so they need no sign-in.
- `runs_folder` is the history folder under the project root. `now` is the aware local time.
- `installed_crontab` gets the crontab text and its zone through the jobs router's live inputs. It returns nothing for both when neither source answers, and the page then says its schedule is unknown.
- `snapshot_now` builds the status snapshot with that schedule, with the time shifted into the crontab's zone.
- `get_status` serves `/api/duplicate-check/status`, `get_job_summary` serves `/api/duplicate-check/job-summary` as a job-summary/1 record, and `get_page` serves `/app/duplicate-check` as HTML that browsers revalidate on each load.
