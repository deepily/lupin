---
capability: rest-cron-job-switches
---
# Scheduled-job switches: the API and the accordion

Each job in `src/conf/job-registry.json` has one on/off key in `src/conf/lupin-app.ini`, written `cron job <job> enabled = true|false`. Only a job with `cron_managed` true reads it, at its next start through `lupin_mcp.job_run`. For the configuration side see [[configuration]]. For the guard against hand edits see [[cc-hook-cron-switch-guard]].

## Reading and writing
- `cosa.rest.cron_job_switches` reads the key fresh from disk on every call. The configuration manager is a singleton and would keep a stale value. A key that is absent, defined twice or neither true nor false reads as `None`, shown as unknown and never as off.
- `write_switch` is the only function that writes a key. A census test in the unit tier fails on any other writer. It locates the key first, so a key the file lacks or defines twice is refused with nothing written. It then records who flipped it and replaces the line. It never inserts a key.
- The record is `cron-job-switches-state.json` in the folder of the configuration write lock. It holds attribution only: `on`, `at` and `by` for each job. The switch itself is the key in the INI. `read_attribution` reads it with `atomic_json.load_json_dict`.
- `LUPIN_CRON_SWITCH_INI` points the module at another file, and the record then sits beside it. Tests use it so the live file is never touched.

## The endpoint
- `GET /api/cron-jobs` lists one row per registry job: `enabled`, `honoured`, `drift`, `last_changed_by`, `last_changed_at`. `honoured` is false for a job that does not read its switch. `drift` is true when the file disagrees with the record, meaning a hand edit. `caller_is_admin` is true only for an administrator login.
- `PUT /api/cron-jobs/{job}/enabled` takes `{ on: bool }` and needs an administrator login. An API key or a non-admin gets 403, an unknown job 404, and a bad body 422. A job that does not read its switch gets 409, and so does a key the file lacks or defines twice.
- A flip emits the `cron_job_switch_changed` WebSocket event to every client. A failed announcement does not fail the flip.

## The accordion
- The legacy client shows the rows in the Scheduled Jobs section of the notifications page. Its code is `cron-jobs.js`. A row shows the switch, who flipped it last, and a note when `drift` is true.
- Everyone sees the switches. Only an administrator login gets a control that sends the PUT. The control is disabled for a job that does not read its switch and for a key with no value yet.
- The page updates a row when it receives `cron_job_switch_changed`.
