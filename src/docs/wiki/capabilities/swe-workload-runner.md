---
capability: swe-workload-runner
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.swe_workload_runner.login@3e75e65991
  - scripts.swe_workload_runner.get_websocket_session_id@1ee8bfdf5d
  - scripts.swe_workload_runner.submit_task@1ab0706dad
  - scripts.swe_workload_runner.poll_done_queue@08b34d62af
  - scripts.swe_workload_runner.capture_decisions_for_job@e6406dd697
  - scripts.swe_workload_runner.run_workload@ad578ee3a0
  - scripts.swe_workload_runner.main@9a9b16679d
  - scripts.swe_workload_catalog.get_tasks_by_category@9b722ee08d
  - scripts.swe_workload_catalog.get_categories@1233d6f14f
  - scripts.swe_workload_catalog.print_catalog_summary@77edd4ef5d
---
# Software-team workload runner

Submits the workload catalog's tasks to the running server one at a time and captures the proxy decisions each job created. The catalog holds 18 small engineering tasks, three for each of six proxy categories. Each entry carries the expected classification and proxy action, so the capture can check correctness.

## Catalog
- `get_tasks_by_category` returns the tasks of one category, or all of them when the category is `None`.
- `get_categories` returns the sorted unique category names.
- `print_catalog_summary` prints a formatted summary table of the catalog.

## Runner
- `login` logs in through the auth endpoint with the mock-jobs test email and password from the environment, and returns the token and headers. Missing variables raise `ValueError`.
- `get_websocket_session_id` gets a WebSocket session id for notifications, falling back to `workload-runner`.
- `submit_task` submits one task through `POST /api/v2/submit` with the `agent router go to swe team` command. It runs as a dry run unless `--live` is given. It returns the job id, or an error message.
- `poll_done_queue` polls the done queue every 2 seconds until the job appears or the timeout passes, 120 seconds by default.
- `capture_decisions_for_job` queries PostgreSQL for every proxy decision the job created. It returns an empty list on failure.
- `run_workload` authenticates, submits each task and waits for it to finish before the next one, then captures the decisions. It writes a JSONL manifest under `io/decision-proxies/` and returns the results with the manifest path.
- `main` parses `--category`, `--limit`, `--live` and `--trust-mode`, and runs the workload. It needs the server on port 7999.
